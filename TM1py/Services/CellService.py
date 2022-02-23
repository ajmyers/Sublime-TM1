# -*- coding: utf-8 -*-
import asyncio
import csv
import functools
import itertools
import json
import uuid
import warnings
from collections import OrderedDict
from concurrent.futures.thread import ThreadPoolExecutor
from io import StringIO
from typing import List, Union, Dict, Iterable, Tuple, Optional

import ijson
from mdxpy import MdxHierarchySet, MdxBuilder
from requests import Response

from TM1py.Exceptions.Exceptions import TM1pyException, TM1pyWritePartialFailureException, TM1pyWriteFailureException, \
    TM1pyRestException
from TM1py.Objects.MDXView import MDXView
from TM1py.Objects.Process import Process
from TM1py.Services.ObjectService import ObjectService
from TM1py.Services.RestService import RestService
from TM1py.Services.SandboxService import SandboxService
from TM1py.Services.ViewService import ViewService
from TM1py.Utils import Utils, CaseAndSpaceInsensitiveSet, format_url, add_url_parameters
from TM1py.Utils.Utils import build_pandas_dataframe_from_cellset, dimension_name_from_element_unique_name, \
    CaseAndSpaceInsensitiveDict, wrap_in_curly_braces, CaseAndSpaceInsensitiveTuplesDict, \
    abbreviate_mdx, build_csv_from_cellset_dict, require_version, require_pandas, build_cellset_from_pandas_dataframe, \
    case_and_space_insensitive_equals, get_cube, resembles_mdx, require_admin, extract_compact_json_cellset, \
    cell_is_updateable, build_mdx_from_cellset, build_mdx_and_values_from_cellset, \
    dimension_names_from_element_unique_names

try:
    import pandas as pd

    _has_pandas = True
except ImportError:
    _has_pandas = False


def tidy_cellset(func):
    """ Higher order function to tidy up cellset after usage
    """

    @functools.wraps(func)
    def wrapper(self, cellset_id, *args, **kwargs):
        try:
            return func(self, cellset_id, *args, **kwargs)

        finally:
            if kwargs.get("delete_cellset", True):
                sandbox_name = kwargs.get("sandbox_name", None)
                try:
                    self.delete_cellset(cellset_id=cellset_id, sandbox_name=sandbox_name)

                except TM1pyRestException as ex:
                    # Fail silently if cellset is already removed
                    if not ex.status_code == 404:
                        raise ex

    return wrapper


def manage_transaction_log(func):
    """ Control state of transaction log during and after write operation for a given cube through:
    `deactivate_transaction_log` and `reactivate_transaction_log`.

    Decorated function must have either `cube_name` or `mdx` as first argument or keyword argument
    """

    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        if "cube_name" in kwargs:
            cube_name = kwargs["cube_name"]
        elif "mdx" in kwargs:
            cube_name = get_cube(kwargs["mdx"])
        else:
            arg = args[0]
            if resembles_mdx(arg):
                cube_name = get_cube(arg)
            else:
                cube_name = arg

        deactivate_transaction_log = kwargs.pop("deactivate_transaction_log", False)
        reactivate_transaction_log = kwargs.pop("reactivate_transaction_log", False)
        try:

            if deactivate_transaction_log:
                self.deactivate_transactionlog(cube_name)
            return func(self, *args, **kwargs)

        finally:
            if reactivate_transaction_log:
                self.activate_transactionlog(cube_name)

    return wrapper


def manage_changeset(func):
    """ Control the start and end of change sets which goups write events together in the TM1 transaction log.

    Decorated function working with all non-TI based writing methods
    """

    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        if kwargs.get("use_changeset", False):
            try:
                changeset = self.begin_changeset()
                kwargs["changeset"] = changeset
                return func(self, *args, **kwargs)
            finally:
                self.end_changeset(changeset)
        else:
            return func(self, *args, **kwargs)

    return wrapper


def odata_compact_json(return_as_dict: bool):
    """ Higher order function to manage header and response when using compact JSON

        Applies when decorated function has `use_compact_json` argument set to True

        Currently only supports responses with only cell properties and where they are explicitly specified:
            * Cellsets('...')?$expand=Axes(...),Cells($select=Ordinal,Value...) does NOT work !
            * Cellsets('...')?$expand=Cells does NOT work !
            * Cellsets('...')?$expand=Cells($select=Ordinal,Value...) works !

    """

    def wrap(func):
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):

            if not kwargs.get("use_compact_json", False):
                return func(self, *args, **kwargs)

            # Update Accept Header
            original_header = self._rest.add_compact_json_header()

            try:
                response = func(self, *args, **kwargs)
                context = response['@odata.context']

                if context.startswith('$metadata#Cellsets'):
                    return extract_compact_json_cellset(context, response, return_as_dict)

                else:
                    raise NotImplementedError('odata_compact_json decorator must only be used on cellsets')

            finally:
                # Restore original header
                self._rest.add_http_header('Accept', original_header)

        return wrapper

    return wrap


class CellService(ObjectService):
    """ Service to handle Read and Write operations to TM1 cubes

    """

    def __init__(self, tm1_rest: RestService):
        """

        :param tm1_rest: instance of RestService
        """
        super().__init__(tm1_rest)

    def get_value(self, cube_name: str, element_string: str, dimensions: List[str] = None, sandbox_name: str = None,
                  **kwargs) -> Union[str, float]:
        """ Element_String describes the Dimension-Hierarchy-Element arrangement

        :param cube_name: Name of the cube
        :param element_string: "Hierarchy1::Element1 && Hierarchy2::Element4, Element9, Element2"
            - Dimensions are not specified! They are derived from the position.
            - The , separates the element-selections
            - If more than one hierarchy is selected per dimension && splits the elementselections
            - If no Hierarchy is specified. Default Hierarchy will be addressed
        :param dimensions: List of dimension names in correct order
        :param sandbox_name: str
        :return:
        """
        mdx_template = "SELECT {} ON ROWS, {} ON COLUMNS FROM [{}]"
        mdx_rows_list = []
        from TM1py.Services.CubeService import CubeService
        if not dimensions:
            dimensions = CubeService(self._rest).get(cube_name).dimensions
        element_selections = element_string.split(',')

        # Build the ON ROWS statement:
        # Loop through the comma separated element selection, except for the last one
        for dimension_name, element_selection in zip(dimensions[:-1], element_selections[:-1]):
            if "&&" not in element_selection:
                if '::' in element_selection:
                    hierarchy_name, element_name = element_selection.split("::")
                else:
                    hierarchy_name = dimension_name
                    element_name = element_selection

                mdx_rows_list.append("{[" + dimension_name + "].[" + hierarchy_name + "].[" + element_name + "]}")

            else:
                for element_selection_part in element_selection.split('&&'):
                    hierarchy_name, element_name = element_selection_part.split('::')
                    mdx_rows_list.append("{[" + dimension_name + "].[" + hierarchy_name + "].[" + element_name + "]}")

        mdx_rows = "*".join(mdx_rows_list)

        # Build the ON COLUMNS statement from last dimension
        mdx_columns = ""
        element_selection = element_selections[-1]
        dimension_name = dimensions[-1]
        if "&&" not in element_selection:
            if '::' in element_selection:
                hierarchy_name, element_name = element_selection.split("::")
            else:
                hierarchy_name = dimension_name
                element_name = element_selection
            mdx_columns = "{[" + dimension_name + "].[" + hierarchy_name + "].[" + element_name + "]}"

        else:
            mdx_columns_list = []
            for element_selection_part in element_selections[-1].split('&&'):
                hierarchy_name, element_name = element_selection_part.split('::')
                mdx_columns_list.append("{[" + dimension_name + "].[" + hierarchy_name + "].[" + element_name + "]}")
                mdx_columns = "*".join(mdx_columns_list)

        # Construct final MDX
        mdx = mdx_template.format(mdx_rows, mdx_columns, cube_name)

        # Execute MDX
        cellset = dict(self.execute_mdx(mdx=mdx, sandbox_name=sandbox_name, **kwargs))
        return next(iter(cellset.values()))["Value"]

    def relative_proportional_spread(
            self,
            value: float,
            cube: str,
            unique_element_names: Iterable[str],
            reference_unique_element_names: Iterable[str],
            reference_cube: str = None,
            sandbox_name: str = None,
            **kwargs) -> Response:
        """ Execute relative proportional spread

        :param value: value to be spread
        :param cube: name of the cube
        :param unique_element_names: target cell coordinates as unique element names (e.g. ["[d1].[c1]","[d2].[e3]"])
        :param reference_cube: name of the reference cube. Can be None
        :param reference_unique_element_names: reference cell coordinates as unique element names
        :param sandbox_name: str
        :return:
        """
        mdx = """
        SELECT
        {{ {rows} }} ON 0
        FROM [{cube}]
        """.format(rows="}*{".join(unique_element_names), cube=cube)
        cellset_id = self.create_cellset(mdx=mdx, sandbox_name=sandbox_name, **kwargs)

        payload = {
            "BeginOrdinal": 0,
            "Value": "RP" + str(value),
            "ReferenceCell@odata.bind": list(),
            "ReferenceCube@odata.bind":
                format_url("Cubes('{}')", reference_cube if reference_cube else cube)}
        for unique_element_name in reference_unique_element_names:
            payload["ReferenceCell@odata.bind"].append(
                format_url(
                    "Dimensions('{}')/Hierarchies('{}')/Elements('{}')",
                    *Utils.dimension_hierarchy_element_tuple_from_unique_name(unique_element_name)))

        return self._post_against_cellset(cellset_id=cellset_id, payload=payload, delete_cellset=True,
                                          sandbox_name=sandbox_name, **kwargs)

    def clear_spread(
            self,
            cube: str,
            unique_element_names: Iterable[str],
            sandbox_name: str = None,
            **kwargs) -> Response:
        """ Execute clear spread
        :param cube: name of the cube
        :param unique_element_names: target cell coordinates as unique element names (e.g. ["[d1].[c1]","[d2].[e3]"])
        :param sandbox_name: str
        :return:
        """
        mdx = """
        SELECT
        {{ {rows} }} ON 0
        FROM [{cube}]
        """.format(rows="}*{".join(unique_element_names), cube=cube)
        cellset_id = self.create_cellset(mdx=mdx, sandbox_name=sandbox_name, **kwargs)

        payload = {
            "BeginOrdinal": 0,
            "Value": "C",
            "ReferenceCell@odata.bind": list()}
        for unique_element_name in unique_element_names:
            payload["ReferenceCell@odata.bind"].append(
                format_url(
                    "Dimensions('{}')/Hierarchies('{}')/Elements('{}')",
                    *Utils.dimension_hierarchy_element_tuple_from_unique_name(unique_element_name)))

        return self._post_against_cellset(cellset_id=cellset_id, payload=payload, delete_cellset=True,
                                          sandbox_name=sandbox_name, **kwargs)

    @require_admin
    @require_version(version="11.7")
    def clear(self, cube: str, **kwargs):
        """
        Takes the cube name and keyword argument pairs of dimensions and expressions:
        `tm1.cells.clear(cube="Sales", product="{[Product].[ABC]}", time="{[Time].[2020].Children}")`

        :param cube: name of the cube
        :param kwargs: keyword argument pairs of dimension names and mdx set expressions
        :return:
        """
        cube_service = self.get_cube_service()
        dimension_names = CaseAndSpaceInsensitiveSet(*cube_service.get_dimension_names(cube_name=cube))
        dimension_expression_pairs = CaseAndSpaceInsensitiveDict()

        for kwarg in kwargs:
            if kwarg in dimension_names:
                dimension_expression_pairs[kwarg] = wrap_in_curly_braces(kwargs[kwarg])

        for dimension_name in dimension_names:
            if dimension_name not in dimension_expression_pairs:
                expression = MdxHierarchySet.tm1_subset_all(dimension_name).filter_by_level(0).to_mdx()
                dimension_expression_pairs[dimension_name] = expression

        mdx_builder = MdxBuilder.from_cube(cube).columns_non_empty()
        for dimension, expression in dimension_expression_pairs.items():
            hierarchy_set = MdxHierarchySet.from_str(dimension=dimension, hierarchy=dimension, mdx=expression)
            mdx_builder.add_hierarchy_set_to_column_axis(hierarchy_set)

        return self.clear_with_mdx(cube=cube, mdx=mdx_builder.to_mdx(), **kwargs)

    @require_admin
    @require_version(version="11.7")
    def clear_with_mdx(self, cube: str, mdx: str, sandbox_name: str = None, **kwargs):
        """ clear a slice in a cube based on an MDX query.
        Function requires admin permissions, since TM1py uses an unbound TI with a `ViewZeroOut` statement.

        :param cube: name of the cube
        :param mdx: a valid MDX query
        :param sandbox_name: a valid existing sandbox for the current user
        :param kwargs:
        :return:
        """
        view_service = ViewService(self._rest)

        enable_sandbox = self.generate_enable_sandbox_ti(sandbox_name)

        view_name = "".join(['}TM1py', str(uuid.uuid4())])
        view_service.create(MDXView(cube_name=cube, view_name=view_name, MDX=mdx))

        try:
            code = f"ViewZeroOut('{cube}','{view_name}');"
            process = Process(name="")
            process.prolog_procedure = enable_sandbox
            process.epilog_procedure = code

            success, _, _ = self.execute_unbound_process(process, **kwargs)
            if not success:
                raise TM1pyException(f"Failed to clear cube: '{cube}' with mdx: '{abbreviate_mdx(mdx, 100)}'")
        finally:
            if view_service.exists(cube, view_name, private=False):
                view_service.delete(cube, view_name, private=False)

    @tidy_cellset
    def _post_against_cellset(self, cellset_id: str, payload: Dict, sandbox_name: str = None, **kwargs) -> Response:
        """ Execute a post request against a cellset

        :param cellset_id:
        :param payload:
        :param sandbox_name: str
        :param kwargs:
        :return:
        """
        url = format_url("/api/v1/Cellsets('{}')/tm1.Update", cellset_id)
        url = add_url_parameters(url, **{"!sandbox": sandbox_name})
        return self._rest.POST(url=url, data=json.dumps(payload), **kwargs)

    def get_dimension_names_for_writing(self, cube_name: str, **kwargs) -> List[str]:
        """ Get dimensions of a cube. Skip sandbox dimension

        :param cube_name:
        :param kwargs:
        :return:
        """
        from TM1py.Services import CubeService
        cube_service = CubeService(self._rest)
        dimensions = cube_service.get_dimension_names(cube_name, True, **kwargs)
        return dimensions

    @require_pandas
    def write_dataframe(self, cube_name: str, data: 'pd.DataFrame', dimensions: Iterable[str] = None,
                        increment: bool = False, deactivate_transaction_log: bool = False,
                        reactivate_transaction_log: bool = False, sandbox_name: str = None,
                        use_ti: bool = False, use_changeset: bool = False, precision: int = 8,
                        skip_non_updateable: bool = False, measure_dimension_elements: Dict = None, **kwargs) -> str:
        """
        Function expects same shape as `execute_mdx_dataframe` returns.
        Column order must match dimensions in the target cube with an additional column for the values.
        Column names are not relevant.
        :param cube_name:
        :param data: Pandas Data Frame
        :param dimensions:
        :param increment:
        :param deactivate_transaction_log:
        :param reactivate_transaction_log:
        :param sandbox_name:
        :param use_ti:
        :param use_changeset: Enable ChangesetID: True or False
        :param precision: max precision when writhing through unbound process.
        Necessary when dealing with large numbers to avoid "number too long" TI syntax error.
        :param skip_non_updateable skip cells that are not updateable (e.g. rule derived or consolidated)
        :param measure_dimension_elements: dictionary of measure elements and their types to improve
        performance when `use_ti` is `True`.
        When all written values are numeric you can pass a default dict with default key 'Numeric'
        :return: changeset or None
        """
        if not isinstance(data, pd.DataFrame):
            raise ValueError("argument 'data' must of type DataFrame")

        if not dimensions:
            dimensions = self.get_dimension_names_for_writing(cube_name=cube_name)

        if not len(data.columns) == len(dimensions) + 1:
            raise ValueError("Number of columns in 'data' DataFrame must be number of dimensions in cube + 1")

        cells = build_cellset_from_pandas_dataframe(data)

        return self.write(cube_name=cube_name,
                          cellset_as_dict=cells,
                          dimensions=dimensions,
                          increment=increment,
                          deactivate_transaction_log=deactivate_transaction_log,
                          reactivate_transaction_log=reactivate_transaction_log,
                          sandbox_name=sandbox_name,
                          use_ti=use_ti,
                          use_changeset=use_changeset,
                          precision=precision,
                          skip_non_updateable=skip_non_updateable,
                          measure_dimension_elements=measure_dimension_elements,
                          **kwargs)

    @manage_transaction_log
    def write_async(self, cube_name: str, cells: Dict, slice_size: int, max_workers: int,
                    dimensions: Iterable[str] = None, increment: bool = False,
                    deactivate_transaction_log: bool = False, reactivate_transaction_log: bool = False,
                    sandbox_name: str = None, precision: int = 8, **kwargs) -> Optional[str]:
        """ Write asynchronously

        :param cube_name:
        :param cells:
        :param slice_size:
        :param max_workers:
        :param dimensions:
        :param increment:
        :param deactivate_transaction_log:
        :param reactivate_transaction_log:
        :param sandbox_name:
        :param precision: max precision when writhing through unbound process.
        Necessary to decrease when dealing with large numbers to avoid "number too long" TI syntax error.
        :param kwargs:
        :return:
        """

        if not dimensions:
            dimensions = self.get_dimension_names_for_writing(cube_name=cube_name)

        def _chunks(data: Dict):
            it = iter(data)
            for _ in range(0, len(data), slice_size):
                yield {k: data[k] for k in itertools.islice(it, slice_size)}

        def _write(chunk: Dict):
            return self.write(cube_name=cube_name, cellset_as_dict=chunk, dimensions=dimensions, increment=increment,
                              use_ti=True, sandbox_name=sandbox_name, precision=precision, **kwargs)

        async def _write_async(data: Dict):
            loop = asyncio.get_event_loop()
            failures = []

            with ThreadPoolExecutor(max_workers) as executor:
                futures = [loop.run_in_executor(executor, _write, chunk) for chunk in _chunks(data)]

                for future in futures:
                    try:
                        await future
                    except (TM1pyWritePartialFailureException, TM1pyWriteFailureException) as exception:
                        failures.append(exception)

            return failures

        exceptions = asyncio.run(_write_async(cells))
        if not exceptions:
            return

        # merge all failures into one combined Exception
        raise TM1pyWritePartialFailureException(
            statuses=list(itertools.chain(*[exception.statuses for exception in exceptions])),
            error_log_files=list(itertools.chain(*[exception.error_log_files for exception in exceptions])),
            attempts=sum([exception.attempts if isinstance(exception, TM1pyWritePartialFailureException) else 1
                          for exception in exceptions]))

    @require_pandas
    @manage_transaction_log
    def write_dataframe_async(self, cube_name: str, data: 'pd.DataFrame', slice_size_of_dataframe: int,
                              max_workers: int, dimensions: Iterable[str] = None, increment: bool = False,
                              sandbox_name: str = None, deactivate_transaction_log: bool = False,
                              reactivate_transaction_log: bool = False, **kwargs):
        """ Write DataFrame into a cube using unbound TI processes in a multi-threading way. Requires admin permissions.
        For a DataFrame with > 1,000,000 rows, this function will at least save half of runtime compared with `write_dataframe` function.
        Column order must match dimensions in the target cube with an additional column for the values.
        Column names are not relevant.
        :param cube_name:
        :param data: Pandas Data Frame
        :param slice_size_of_dataframe: Number of rows for each DataFrame slice, e.g. 10000
        :param max_workers: Max number of threads, e.g. 14
        :param dimensions:
        :param increment: increment or update cell values. Defaults to False.
        :param sandbox_name: name of the sandbox or None
        :param deactivate_transaction_log:
        :param reactivate_transaction_log:
        :return: the Future’s result or raise exception.
        """
        if not isinstance(data, pd.DataFrame):
            raise ValueError("argument 'data' must of type DataFrame")

        if not dimensions:
            dimensions = self.get_dimension_names_for_writing(cube_name=cube_name)

        if not len(data.columns) == len(dimensions) + 1:
            raise ValueError("Number of columns in 'data' DataFrame must be number of dimensions in cube + 1")

        def _chunks(df: 'pd.DataFrame'):
            return [df.iloc[i:i + slice_size_of_dataframe] for i in range(0, df.shape[0], slice_size_of_dataframe)]

        def _write(chunk: 'pd.DataFrame'):
            return self.write_dataframe(cube_name=cube_name, data=chunk, dimensions=dimensions, increment=increment,
                                        use_ti=True, sandbox_name=sandbox_name, **kwargs)

        async def _write_async(df: 'pd.DataFrame'):
            loop = asyncio.get_event_loop()
            failures = []

            with ThreadPoolExecutor(max_workers) as executor:
                futures = [loop.run_in_executor(executor, _write, chunk) for chunk in _chunks(df)]

                for future in futures:
                    try:
                        await future
                    except (TM1pyWritePartialFailureException, TM1pyWriteFailureException) as exception:
                        failures.append(exception)

            return failures

        exceptions = asyncio.run(_write_async(data))
        if not exceptions:
            return

        # merge all failures into one combined Exception
        raise TM1pyWritePartialFailureException(
            statuses=list(itertools.chain(*[exception.statuses for exception in exceptions])),
            error_log_files=list(itertools.chain(*[exception.error_log_files for exception in exceptions])),
            attempts=sum([exception.attempts for exception in exceptions]))

    def write_value(self, value: Union[str, float], cube_name: str, element_tuple: Iterable,
                    dimensions: Iterable[str] = None, sandbox_name: str = None, **kwargs) -> Response:
        """ Write value into cube at specified coordinates

        :param value: the actual value
        :param cube_name: name of the target cube
        :param element_tuple: target coordinates
        :param dimensions: optional. Dimension names in their natural order. Will speed up the execution!
        :param sandbox_name: str
        :return: response
        """
        if not dimensions:
            dimensions = self.get_dimension_names_for_writing(cube_name=cube_name)
        url = format_url("/api/v1/Cubes('{}')/tm1.Update", cube_name)
        url = add_url_parameters(url, **{"!sandbox": sandbox_name})
        body_as_dict = OrderedDict()
        body_as_dict["Cells"] = [{}]
        body_as_dict["Cells"][0]["Tuple@odata.bind"] = [
            format_url("Dimensions('{}')/Hierarchies('{}')/Elements('{}')", dim, dim, elem)
            for dim, elem
            in zip(dimensions, element_tuple)]
        body_as_dict["Value"] = str(value) if value else ""
        data = json.dumps(body_as_dict, ensure_ascii=False)
        return self._rest.POST(url=url, data=data, **kwargs)

    def write(self, cube_name: str, cellset_as_dict: Dict, dimensions: Iterable[str] = None, increment: bool = False,
              deactivate_transaction_log: bool = False, reactivate_transaction_log: bool = False,
              sandbox_name: str = None, use_ti=False, use_changeset: bool = False, precision: int = 8,
              skip_non_updateable: bool = False, measure_dimension_elements: Dict = None, **kwargs) -> Optional[str]:
        """ Write values to a cube

        Same signature as `write_values` method, but faster since it uses `write_values_through_cellset`
        behind the scenes.

        Supports incrementing cell values through optional `increment` argument
        Spreading through spreading shortcuts is not supported!

        :param cube_name: name of the cube
        :param cellset_as_dict: {(elem_a, elem_b, elem_c): 243, (elem_d, elem_e, elem_f) : 109}
        :param dimensions: optional. Dimension names in their natural order. Will speed up the execution!
        :param increment: increment or update cell values
        :param deactivate_transaction_log: deactivate before writing
        :param reactivate_transaction_log: reactivate after writing
        :param sandbox_name: str
        :param use_ti: Use unbound process to write. Requires admin permissions. causes massive performance improvement.
        :param use_changeset: Enable ChangesetID: True or False
        :param precision: max precision when writhing through unbound process.
        Necessary when dealing with large numbers to avoid "number too long" TI syntax error.
        :param skip_non_updateable skip cells that are not updateable (e.g. rule derived or consolidated)
        :param measure_dimension_elements: dictionary of measure elements and their types to improve
        performance when `use_ti` is `True`.
        When all written values are numeric you can pass a default dict with default key 'Numeric'
        :return: changeset or None
        """

        if use_ti:
            return self.write_through_unbound_process(
                cube_name=cube_name,
                cellset_as_dict=cellset_as_dict,
                increment=increment,
                sandbox_name=sandbox_name,
                deactivate_transaction_log=deactivate_transaction_log,
                reactivate_transaction_log=reactivate_transaction_log,
                precision=precision,
                skip_non_updateable=skip_non_updateable,
                measure_dimension_elements=measure_dimension_elements,
                **kwargs)

        return self.write_through_cellset(cube_name, cellset_as_dict, dimensions, increment, deactivate_transaction_log,
                                          reactivate_transaction_log, sandbox_name, use_changeset, skip_non_updateable,
                                          **kwargs)

    def write_through_cellset(self, cube_name: str, cellset_as_dict: Dict, dimensions: Iterable[str] = None,
                              increment: bool = False, deactivate_transaction_log: bool = False,
                              reactivate_transaction_log: bool = False, sandbox_name: str = None,
                              use_changeset: bool = False, skip_non_updateable: bool = False, **kwargs) -> str:
        if not dimensions:
            dimensions = self.get_dimension_names_for_writing(cube_name=cube_name, **kwargs)

        if skip_non_updateable:
            cellset_as_dict = self.drop_non_updateable_cells(cellset_as_dict, cube_name, dimensions)

        mdx, values = build_mdx_and_values_from_cellset(cellset_as_dict, cube_name, dimensions)
        return self.write_values_through_cellset(
            mdx=mdx,
            values=values,
            increment=increment,
            deactivate_transaction_log=deactivate_transaction_log,
            reactivate_transaction_log=reactivate_transaction_log,
            sandbox_name=sandbox_name,
            use_changeset=use_changeset,
            **kwargs)

    def drop_non_updateable_cells(self, cells: Dict, cube_name: str, dimensions: List[str]):
        mdx = build_mdx_from_cellset(cells, cube_name, dimensions)
        updateable_cells = CaseAndSpaceInsensitiveTuplesDict()

        cells_with_updateable_flag = self.execute_mdx(
            mdx,
            # Issue in TM1 Server 11.8: Updateable property is not correct if Value property is not retrieved
            cell_properties=["Updateable", "Value"],
            element_unique_names=False,
            skip_consolidated_cells=True,
            skip_rule_derived_cells=True)

        for elements, cell in cells_with_updateable_flag.items():
            # skip sandbox element
            if len(elements) > len(dimensions):
                elements = elements[1:]

            if cell_is_updateable(cell):
                updateable_cells[elements] = cells[elements]
        return updateable_cells

    @require_admin
    @manage_transaction_log
    def write_through_unbound_process(self, cube_name: str, cellset_as_dict: Dict, increment: bool = False,
                                      sandbox_name: str = None, precision: int = 8, skip_non_updateable: bool = False,
                                      measure_dimension_elements: Dict = None, is_attribute_cube: bool = None,
                                      **kwargs):
        """
        Writes data back to TM1 via an unbound TI process
        :param cube_name: str
        :param cellset_as_dict:
        :param increment: increment or update cell values
        :param sandbox_name: str
        :param precision: max precision when writhing through unbound process.
        :param skip_non_updateable skip cells that are not updateable (e.g. rule derived or consolidated)
        :param measure_dimension_elements: pass dictionary of measure elements and their types to improve performance
        When all written values are numeric you can pass a defaultdict with default key: 'Numeric'
        :param is_attribute_cube bool or None
        :param kwargs:
        :return: Success: bool, Messages: list, ChangeSet: None
        """
        if is_attribute_cube is None:
            is_attribute_cube = cube_name.lower().startswith("}elementattributes_")

        enable_sandbox = self.generate_enable_sandbox_ti(sandbox_name)

        successes = list()
        statuses = list()
        log_files = list()

        if not measure_dimension_elements:
            measure_dimension_elements = self.get_elements_from_all_measure_hierarchies(cube_name)

        if is_attribute_cube:
            statements = self._build_attribute_update_statements(
                cube_name=cube_name,
                cellset_as_dict=cellset_as_dict,
                precision=precision,
                measure_dimension_elements=measure_dimension_elements,
                skip_non_updateable=skip_non_updateable)

        else:
            statements = self._build_cell_update_statements(
                cube_name=cube_name,
                cellset_as_dict=cellset_as_dict,
                increment=increment,
                measure_dimension_elements=measure_dimension_elements,
                precision=precision,
                skip_non_updateable=skip_non_updateable)

        chunk = list()
        for n, statement in enumerate(statements):
            chunk.append(statement)
            if n > 0 and n % (Process.MAX_STATEMENTS * 2) == 0:
                success, status, log_file = self._execute_write_statements(chunk, enable_sandbox, kwargs)
                successes.append(success)
                if not success:
                    statuses.append(status)
                    log_files.append(log_file)

                chunk = list()

        success, status, log_file = self._execute_write_statements(chunk, enable_sandbox, kwargs)
        successes.append(success)
        if not success:
            statuses.append(status)
            log_files.append(log_file)

        if not any(successes):
            if 'HasMinorErrors' in statuses:
                raise TM1pyWritePartialFailureException(statuses, log_files, len(successes))

            raise TM1pyWriteFailureException(statuses, log_files)

        if not all(successes):
            raise TM1pyWritePartialFailureException(statuses, log_files, len(successes))

    @staticmethod
    def _build_attribute_update_statements(cube_name, cellset_as_dict, precision: int = 8,
                                           skip_non_updateable: bool = False, measure_dimension_elements: Dict = None):
        dimension_name = cube_name[19:]
        statements = list()

        for coordinates, value in cellset_as_dict.items():
            # default to 'Numeric' so that not existing elements trigger minor error during TI execution
            raw_element_name = coordinates[0]
            if ":" in raw_element_name:
                hierarchy_name, element_name = raw_element_name.split(":")
            else:
                element_name = raw_element_name
                hierarchy_name = dimension_name
            attribute_name = coordinates[-1]

            try:
                attribute_type = measure_dimension_elements[attribute_name]

            except KeyError:
                if ":" in attribute_name:
                    attribute_name = attribute_name.split(":")[1]
                    attribute_type = measure_dimension_elements.get(attribute_name, 'String')
                else:
                    attribute_type = 'String'

            if attribute_type == 'Numeric':
                function_str = "ElementAttrPutN("
                # number strings must not exceed float range
                if isinstance(value, str):
                    try:
                        value_str = format(float(value), f'.{precision}f')
                    except ValueError:
                        value_str = f'{value}'
                elif value is None:
                    value_str = '0'
                else:
                    value_str = format(value, f'.{precision}f')

            # by default assume String for attribute values
            else:
                function_str = 'ElementAttrPutS('
                value_str = str(value).replace("'", "''").replace('\r', '').replace('\n', '')
                value_str = f"'{value_str}'"

            value_str += ","

            comma_separated_args = ",".join(
                "'" + element.replace("'", "''") + "'"
                for element
                in [dimension_name, hierarchy_name, element_name, attribute_name])

            cell_is_updateable_pre = ""
            cell_is_updateable_post = ";"
            if skip_non_updateable:
                cell_is_updateable_pre = f"IF(CellIsUpdateable('{cube_name}', '{raw_element_name}', '{attribute_name}')=1,"
                cell_is_updateable_post = ",0);"

            statement = "".join([
                cell_is_updateable_pre,
                function_str,
                value_str,
                comma_separated_args,
                ")",
                cell_is_updateable_post])

            statements.append(statement)

        return statements

    @staticmethod
    def _build_cell_update_statements(cube_name: str, cellset_as_dict: Dict, increment: bool,
                                      measure_dimension_elements: Dict, precision: int, skip_non_updateable: bool):
        statements = list()

        for coordinates, value in cellset_as_dict.items():
            # default to 'Numeric' so that not existing elements trigger minor error during TI execution
            measure_element = coordinates[-1]
            try:
                element_type = measure_dimension_elements[measure_element]

            except KeyError:
                if ":" in measure_element:
                    measure_element = measure_element.split(":")[1]
                    element_type = measure_dimension_elements.get(measure_element, 'Numeric')
                else:
                    element_type = 'Numeric'

            if element_type == 'String':
                function_str = 'CellPutS('
                value_str = str(value).replace("'", "''").replace('\r', '').replace('\n', '')
                value_str = f"'{value_str}'"

            # by default assume numeric, to trigger minor errors on write operations to C elements
            else:
                function_str = "CellIncrementN(" if increment else "CellPutN("
                # number strings must not exceed float range
                if isinstance(value, str):
                    try:
                        value_str = format(float(value), f'.{precision}f')
                    except ValueError:
                        value_str = f'{value}'
                elif value is None:
                    value_str = '0'
                else:
                    value_str = format(value, f'.{precision}f')

            comma_separated_elements = ",".join("'" + element.replace("'", "''") + "'" for element in coordinates)

            cell_is_updateable_pre = ""
            cell_is_updateable_post = ";"
            if skip_non_updateable:
                cell_is_updateable_pre = f"IF(CellIsUpdateable('{cube_name}', {comma_separated_elements})=1,"
                cell_is_updateable_post = ",0);"

            statement = "".join([
                cell_is_updateable_pre,
                function_str,
                value_str,
                f",'{cube_name}',",
                comma_separated_elements,
                ")",
                cell_is_updateable_post])

            statements.append(statement)

        return statements

    def generate_enable_sandbox_ti(self, sandbox_name):
        if self._rest.sandboxing_disabled:
            enable_sandbox = ""

        elif sandbox_name:
            if not self.sandbox_exists(sandbox_name):
                raise ValueError(f"Sandbox '{sandbox_name}' does not exist")

            enable_sandbox = f"ServerActiveSandboxSet('{sandbox_name}');SetUseActiveSandboxProperty(1);"

        else:
            enable_sandbox = f"ServerActiveSandboxSet('');SetUseActiveSandboxProperty(0);"
        return enable_sandbox

    def get_elements_from_all_measure_hierarchies(self, cube_name: str) -> Dict[str, str]:
        from TM1py.Services.CubeService import CubeService
        from TM1py.Services.ElementService import ElementService

        cube_service = CubeService(self._rest)
        element_service = ElementService(self._rest)

        measure_dimension = cube_service.get_measure_dimension(cube_name=cube_name)
        return element_service.get_element_types_from_all_hierarchies(dimension_name=measure_dimension)

    def _execute_write_statements(self, statements: List[str], enable_sandbox: str, kwargs) -> Tuple[bool, str, str]:
        process = Process(
            name="",
            prolog_procedure=enable_sandbox + "\r".join(statements[:Process.MAX_STATEMENTS]),
            epilog_procedure="\r".join(statements[Process.MAX_STATEMENTS:]))

        return self.execute_unbound_process(process, **kwargs)

    def get_element_service(self):
        from TM1py import ElementService
        return ElementService(self._rest)

    def get_cube_service(self):
        from TM1py import CubeService
        return CubeService(self._rest)

    def execute_unbound_process(self, process: Process, **kwargs) -> Tuple[bool, str, str]:
        from TM1py import ProcessService
        process_service = ProcessService(self._rest)

        return process_service.execute_process_with_return(process, **kwargs)

    def get_error_log_file_content(self, file_name: str, **kwargs) -> str:
        from TM1py import ProcessService
        process_service = ProcessService(self._rest)

        return process_service.get_error_log_file_content(file_name, **kwargs)

    @manage_changeset
    @manage_transaction_log
    def write_values(self, cube_name: str, cellset_as_dict: Dict, dimensions: Iterable[str] = None,
                     sandbox_name: str = None, changeset: str = None, **kwargs) -> str:
        """ Write values to a cube

        For cellsets with > 1000 cells look into `write` or `write_values_through_cellset`
        Supports spreading shortcuts

        :param cube_name: name of the cube
        :param cellset_as_dict: {(elem_a, elem_b, elem_c): 243, (elem_d, elem_e, elem_f) : 109}
        :param dimensions: optional. Dimension names in their natural order. Will speed up the execution!
        :param sandbox_name: str
        :param changeset: str
        :return: Response
        """
        if not dimensions:
            dimensions = self.get_dimension_names_for_writing(cube_name=cube_name, **kwargs)
        url = format_url("/api/v1/Cubes('{}')/tm1.Update", cube_name)
        url = add_url_parameters(url, **{"!sandbox": sandbox_name})
        url = add_url_parameters(url, **{"!ChangeSet": changeset})

        updates = []
        for element_tuple, value in cellset_as_dict.items():
            body_as_dict = OrderedDict()
            body_as_dict["Cells"] = [{}]
            body_as_dict["Cells"][0]["Tuple@odata.bind"] = [
                format_url(
                    "Dimensions('{}')/Hierarchies('{}')/Elements('{}')",
                    dim, dim, elem)
                for dim, elem
                in zip(dimensions, element_tuple)]
            body_as_dict["Value"] = value if value else ""
            updates.append(json.dumps(body_as_dict, ensure_ascii=False))
        updates = '[' + ','.join(updates) + ']'
        self._rest.POST(url=url, data=updates, **kwargs)

        return changeset

    @manage_changeset
    @manage_transaction_log
    def write_values_through_cellset(self, mdx: str, values: Iterable, increment: bool = False,
                                     sandbox_name: str = None, **kwargs) -> str:
        """ Significantly faster than write_values function

        Cellset gets created according to MDX Expression. For instance:
        [[61, 29 ,13],
        [42, 54, 15],
        [17, 28, 81]]

        Each value in the cellset can be addressed through its position: The ordinal integer value.
        Ordinal-enumeration goes from top to bottom from left to right
        Number 61 has Ordinal 0, 29 has Ordinal 1, etc.

        The order of the iterable determines the insertion point in the cellset.
        For instance:
        [91, 85, 72, 68, 51, 42, 35, 28, 11]

        would lead to:
        [[91, 85 ,72],
        [68, 51, 42],
        [35, 28, 11]]

        When writing large datasets into TM1 Cubes it can be convenient to call this function asynchronously.

        :param mdx: Valid MDX Expression.
        :param values: List of values. The Order of the List/ Iterable determines the insertion point in the cellset.
        :param increment: increment or update cells
        :param sandbox_name: str
        :return: changeset: str
        """

        changeset = kwargs.get("changeset")

        cellset_id = self.create_cellset(mdx=mdx, sandbox_name=sandbox_name, **kwargs)
        if increment:
            current_values = self.extract_cellset_values(cellset_id, use_compact_json=True, delete_cellset=False,
                                                         **kwargs)
            values = (x + (y or None) for x, y in zip(values, current_values))

        self.update_cellset(cellset_id=cellset_id, values=values, sandbox_name=sandbox_name, **kwargs)
        return changeset

    @tidy_cellset
    def update_cellset(self, cellset_id: str, values: Iterable, sandbox_name: str = None, changeset: str = None,
                       **kwargs) -> Response:
        """ Write values into cellset

        Number of values must match the number of cells in the cellset

        :param cellset_id:
        :param values: iterable with Numeric and String values
        :param sandbox_name: str
        :param changeset:
        :return:
        """

        url = format_url("/api/v1/Cellsets('{}')/Cells", cellset_id)
        url = add_url_parameters(url, **{"!sandbox": sandbox_name})
        url = add_url_parameters(url, **{"!ChangeSet": changeset})
        data = []
        for o, value in enumerate(values):
            data.append({
                "Ordinal": o,
                "Value": value
            })

        return self._rest.PATCH(url, json.dumps(data, ensure_ascii=False), **kwargs)

    def execute_mdx(self, mdx: str, cell_properties: List[str] = None, top: int = None, skip_contexts: bool = False,
                    skip: int = None, skip_zeros: bool = False, skip_consolidated_cells: bool = False,
                    skip_rule_derived_cells: bool = False, sandbox_name: str = None, element_unique_names: bool = True,
                    skip_cell_properties: bool = False, use_compact_json: bool = False,
                    **kwargs) -> CaseAndSpaceInsensitiveTuplesDict:
        """ Execute MDX and return the cells with their properties

        :param mdx: MDX Query, as string
        :param cell_properties: properties to be queried from the cell. E.g. Value, Ordinal, RuleDerived, ...
        :param top: Int, number of cells to return (counting from top)
        :param skip: Int, number of cells to skip (counting from top)
        :param skip_contexts: skip elements from titles / contexts in response
        :param skip_zeros: skip zeros in cellset (irrespective of zero suppression in MDX / view)
        :param skip_consolidated_cells: skip consolidated cells in cellset
        :param skip_rule_derived_cells: skip rule derived cells in cellset
        :param sandbox_name: str
        :param element_unique_names: '[d1].[h1].[e1]' or 'e1'
        :param skip_cell_properties: cell values in result dictionary, instead of cell_properties dictionary
        :param use_compact_json: bool
        :return: content in sweet concise structure.
        """
        cellset_id = self.create_cellset(mdx=mdx, sandbox_name=sandbox_name, **kwargs)
        return self.extract_cellset(
            cellset_id=cellset_id,
            cell_properties=cell_properties,
            top=top,
            skip=skip,
            skip_contexts=skip_contexts,
            skip_zeros=skip_zeros,
            skip_consolidated_cells=skip_consolidated_cells,
            skip_rule_derived_cells=skip_rule_derived_cells,
            delete_cellset=True,
            sandbox_name=sandbox_name,
            element_unique_names=element_unique_names,
            skip_cell_properties=skip_cell_properties,
            use_compact_json=use_compact_json,
            **kwargs)

    def execute_view(self, cube_name: str, view_name: str, private: bool = False, cell_properties: Iterable[str] = None,
                     top: int = None, skip_contexts: bool = False, skip: int = None, skip_zeros: bool = False,
                     skip_consolidated_cells: bool = False, skip_rule_derived_cells: bool = False,
                     sandbox_name: str = None, element_unique_names: bool = True, skip_cell_properties: bool = False,
                     use_compact_json: bool = False, **kwargs) -> CaseAndSpaceInsensitiveTuplesDict:
        """ get view content as dictionary with sweet and concise structure.
            Works on NativeView and MDXView !

        :param cube_name: String, name of the cube
        :param view_name: String, name of the view
        :param private: True (private) or False (public)
        :param cell_properties: List, cell properties: [Values, Status, HasPicklist, etc.]
        :param private: Boolean
        :param top: Int, number of cells to return (counting from top)
        :param skip: Int, number of cells to skip (counting from top)
        :param skip_contexts: skip elements from titles / contexts in response
        :param skip_zeros: skip zeros in cellset (irrespective of zero suppression in MDX / view)
        :param skip_consolidated_cells: skip consolidated cells in cellset
        :param skip_rule_derived_cells: skip rule derived cells in cellset
        :param element_unique_names: '[d1].[h1].[e1]' or 'e1'
        :param sandbox_name: str
        :param skip_cell_properties: cell values in result dictionary, instead of cell_properties dictionary
        :param use_compact_json: bool
        :return: Dictionary : {([dim1].[elem1], [dim2][elem6]): {'Value':3127.312, 'Ordinal':12}   ....  }
        """
        cellset_id = self.create_cellset_from_view(cube_name=cube_name, view_name=view_name, private=private,
                                                   sandbox_name=sandbox_name, **kwargs)
        return self.extract_cellset(
            cellset_id=cellset_id,
            cell_properties=cell_properties,
            top=top,
            skip=skip,
            skip_contexts=skip_contexts,
            skip_zeros=skip_zeros,
            skip_consolidated_cells=skip_consolidated_cells,
            skip_rule_derived_cells=skip_rule_derived_cells,
            delete_cellset=True,
            sandbox_name=sandbox_name,
            element_unique_names=element_unique_names,
            skip_cell_properties=skip_cell_properties,
            use_compact_json=use_compact_json,
            **kwargs)

    def execute_mdx_raw(
            self,
            mdx: str,
            cell_properties: Iterable[str] = None,
            elem_properties: Iterable[str] = None,
            member_properties: Iterable[str] = None,
            top: int = None,
            skip_contexts: bool = False,
            skip: int = None,
            skip_zeros: bool = False,
            skip_consolidated_cells: bool = False,
            skip_rule_derived_cells: bool = False,
            sandbox_name: str = None,
            include_hierarchies: bool = False,
            use_compact_json: bool = False,
            **kwargs) -> Dict:
        """ Execute MDX and return the raw data from TM1

        :param mdx: String, a valid MDX Query
        :param cell_properties: List of properties to be queried from the cell. E.g. ['Value', 'RuleDerived', ...]
        :param elem_properties: List of properties to be queried from the elements. E.g. ['Name','Attributes', ...]
        :param member_properties: List of properties to be queried from the members. E.g. ['Name','Attributes', ...]
        :param top: Integer limiting the number of cells and the number or rows returned
        :param skip: Integer limiting the number of cells and the number or rows returned
        :param skip_contexts: skip elements from titles / contexts in response
        :param skip_zeros: skip zeros in cellset (irrespective of zero suppression in MDX / view)
        :param skip_consolidated_cells: skip consolidated cells in cellset
        :param skip_rule_derived_cells: skip rule derived cells in cellset
        :param sandbox_name: str
        :param include_hierarchies: retrieve Hierarchies property on Axes
        :param use_compact_json: bool
        :return: Raw format from TM1.
        """
        cellset_id = self.create_cellset(mdx=mdx, sandbox_name=sandbox_name, **kwargs)
        return self.extract_cellset_raw(
            cellset_id=cellset_id,
            cell_properties=cell_properties,
            elem_properties=elem_properties,
            member_properties=member_properties,
            top=top,
            skip=skip,
            delete_cellset=True,
            skip_contexts=skip_contexts,
            skip_zeros=skip_zeros,
            skip_consolidated_cells=skip_consolidated_cells,
            skip_rule_derived_cells=skip_rule_derived_cells,
            sandbox_name=sandbox_name,
            include_hierarchies=include_hierarchies,
            use_compact_json=use_compact_json,
            **kwargs)

    def execute_view_raw(
            self,
            cube_name: str,
            view_name: str,
            private: bool = False,
            cell_properties: Iterable[str] = None,
            elem_properties: Iterable[str] = None,
            member_properties: Iterable[str] = None,
            top: int = None,
            skip_contexts: bool = False,
            skip: int = None,
            skip_zeros: bool = False,
            skip_consolidated_cells: bool = False,
            skip_rule_derived_cells: bool = False,
            sandbox_name: str = None,
            use_compact_json: bool = False,
            **kwargs) -> Dict:
        """ Execute a cube view and return the raw data from TM1


        :param cube_name: String, name of the cube
        :param view_name: String, name of the view
        :param private: True (private) or False (public)
        :param cell_properties: List of properties to be queried from the cell. E.g. ['Value', 'RuleDerived', ...]
        :param elem_properties: List of properties to be queried from the elements. E.g. ['Name','Attributes', ...]
        :param member_properties: List of properties to be queried from the members. E.g. ['Name','Attributes', ...]
        :param top: Integer limiting the number of cells and the number or rows returned
        :param skip_contexts: skip elements from titles / contexts in response
        :param skip: Integer limiting the number of cells and the number or rows returned
        :param skip_zeros: skip zeros in cellset (irrespective of zero suppression in MDX / view)
        :param skip_consolidated_cells: skip consolidated cells in cellset
        :param skip_rule_derived_cells: skip rule derived cells in cellset
        :param sandbox_name: str
        :param use_compact_json: bool
        :return: Raw format from TM1.
        """
        cellset_id = self.create_cellset_from_view(cube_name=cube_name, view_name=view_name, private=private,
                                                   sandbox_name=sandbox_name, **kwargs)
        return self.extract_cellset_raw(
            cellset_id=cellset_id,
            cell_properties=cell_properties,
            elem_properties=elem_properties,
            member_properties=member_properties,
            top=top,
            skip=skip,
            skip_contexts=skip_contexts,
            skip_zeros=skip_zeros,
            skip_rule_derived_cells=skip_rule_derived_cells,
            skip_consolidated_cells=skip_consolidated_cells,
            delete_cellset=True,
            sandbox_name=sandbox_name,
            use_compact_json=use_compact_json,
            **kwargs)

    def execute_mdx_values(self, mdx: str, sandbox_name: str = None, use_compact_json: bool = False,
                           skip_zeros: bool = False, skip_consolidated_cells: bool = False,
                           skip_rule_derived_cells: bool = False, **kwargs) -> List[Union[str, float]]:
        """ Optimized for performance. Query only raw cell values.
        Coordinates are omitted !

        :param mdx: a valid MDX Query
        :param sandbox_name: str
        :param use_compact_json: bool
        :param skip_zeros: bool
        :param skip_consolidated_cells: bool
        :param skip_rule_derived_cells: bool
        :return: List of cell values
        """
        cellset_id = self.create_cellset(mdx=mdx, sandbox_name=sandbox_name, **kwargs)
        return self.extract_cellset_values(cellset_id, delete_cellset=True, sandbox_name=sandbox_name,
                                           skip_zeros=skip_zeros, skip_consolidated_cells=skip_consolidated_cells,
                                           skip_rule_derived_cells=skip_rule_derived_cells,
                                           use_compact_json=use_compact_json, **kwargs)

    def execute_view_values(self, cube_name: str, view_name: str, private: bool = False, sandbox_name: str = None,
                            skip_zeros: bool = False, skip_consolidated_cells: bool = False,
                            skip_rule_derived_cells: bool = False, use_compact_json: bool = False, **kwargs) -> List[
        Union[str, float]]:
        """ Execute view and retrieve only the cell values

        :param cube_name: String, name of the cube
        :param view_name: String, name of the view
        :param private: True (private) or False (public)
        :param sandbox_name: str
        :param use_compact_json: bool
        :param skip_zeros: bool
        :param skip_consolidated_cells: bool
        :param skip_rule_derived_cells: bool
        :param kwargs:
        :return:
        """
        cellset_id = self.create_cellset_from_view(cube_name=cube_name, view_name=view_name, private=private,
                                                   sandbox_name=sandbox_name, **kwargs)
        return self.extract_cellset_values(cellset_id, delete_cellset=True, sandbox_name=sandbox_name,
                                           use_compact_json=use_compact_json, skip_zeros=skip_zeros,
                                           skip_rule_derived_cells=skip_rule_derived_cells,
                                           skip_consolidated_cells=skip_consolidated_cells, **kwargs)

    def execute_mdx_rows_and_values(self, mdx: str, element_unique_names: bool = True, sandbox_name: str = None,
                                    **kwargs) -> CaseAndSpaceInsensitiveTuplesDict:
        """ Execute MDX and retrieve row element names and values in a case and space insensitive dictionary

        :param mdx:
        :param element_unique_names:
        :param sandbox_name: str
        :param kwargs:
        :return:
        """
        cellset_id = self.create_cellset(mdx=mdx, sandbox_name=sandbox_name, **kwargs)
        return self.extract_cellset_rows_and_values(cellset_id, element_unique_names, delete_cellset=True,
                                                    sandbox_name=sandbox_name, **kwargs)

    def execute_view_rows_and_values(self, cube_name: str, view_name: str, private: bool = False,
                                     element_unique_names: bool = True, sandbox_name: str = None,
                                     **kwargs) -> CaseAndSpaceInsensitiveTuplesDict:
        """ Execute cube view and retrieve row element names and values in a case and space insensitive dictionary

        :param cube_name: String, name of the cube
        :param view_name: String, name of the view
        :param private: True (private) or False (public)
        :param element_unique_names:
        :param sandbox_name: str
        :param kwargs:
        :return:
        """
        cellset_id = self.create_cellset_from_view(cube_name=cube_name, view_name=view_name, private=private,
                                                   sandbox_name=sandbox_name, **kwargs)
        return self.extract_cellset_rows_and_values(cellset_id, element_unique_names, delete_cellset=True,
                                                    sandbox_name=sandbox_name, **kwargs)

    def execute_mdx_csv(self, mdx: str, top: int = None, skip: int = None, skip_zeros: bool = True,
                        skip_consolidated_cells: bool = False, skip_rule_derived_cells: bool = False,
                        csv_dialect: 'csv.Dialect' = None, line_separator: str = "\r\n", value_separator: str = ",",
                        sandbox_name: str = None, include_attributes: bool = False, use_iterative_json: bool = False,
                        use_compact_json: bool = False, **kwargs) -> str:
        """ Optimized for performance. Get csv string of coordinates and values.

        :param mdx: Valid MDX Query
        :param top: Int, number of cells to return (counting from top)
        :param skip: Int, number of cells to skip (counting from top)
        :param skip_zeros: skip zeros in cellset (irrespective of zero suppression in MDX / view)
        :param skip_consolidated_cells: skip consolidated cells in cellset
        :param skip_rule_derived_cells: skip rule derived cells in cellset
        :param csv_dialect: provide all csv output settings through standard library csv.Dialect
            If not provided dialect is created based on line_separator and value_separator arguments.
        :param line_separator:
        :param value_separator:
        :param sandbox_name: str
        :param include_attributes: include attribute columns
        :param use_iterative_json: use iterative json parsing to reduce memory consumption significantly.
        Comes at a cost of 3-5% performance.
        :param use_compact_json: bool
        :return: String
        """
        cellset_id = self.create_cellset(mdx, sandbox_name=sandbox_name, **kwargs)

        if use_iterative_json:
            return self.extract_cellset_csv_iter_json(
                cellset_id=cellset_id, top=top, skip=skip, skip_zeros=skip_zeros,
                skip_rule_derived_cells=skip_rule_derived_cells, skip_consolidated_cells=skip_consolidated_cells,
                csv_dialect=csv_dialect, line_separator=line_separator, value_separator=value_separator,
                sandbox_name=sandbox_name, include_attributes=include_attributes, **kwargs)

        return self.extract_cellset_csv(
            cellset_id=cellset_id, top=top, skip=skip, skip_zeros=skip_zeros,
            skip_rule_derived_cells=skip_rule_derived_cells, skip_consolidated_cells=skip_consolidated_cells,
            csv_dialect=csv_dialect, line_separator=line_separator, value_separator=value_separator,
            sandbox_name=sandbox_name, include_attributes=include_attributes,
            use_compact_json=use_compact_json, **kwargs)

    def execute_view_csv(self, cube_name: str, view_name: str, private: bool = False, top: int = None, skip: int = None,
                         skip_zeros: bool = True, skip_consolidated_cells: bool = False,
                         skip_rule_derived_cells: bool = False, csv_dialect: 'csv.Dialect' = None,
                         line_separator: str = "\r\n", value_separator: str = ",", sandbox_name: str = None,
                         use_iterative_json: bool = False, use_compact_json: bool = False, **kwargs) -> str:
        """ Optimized for performance. Get csv string of coordinates and values.

        :param cube_name: String, name of the cube
        :param view_name: String, name of the view
        :param private: True (private) or False (public)
        :param top: Int, number of cells to return (counting from top)
        :param skip: Int, number of cells to skip (counting from top)
        :param skip_zeros: skip zeros in cellset (irrespective of zero suppression in MDX / view)
        :param skip_consolidated_cells: skip consolidated cells in cellset
        :param skip_rule_derived_cells: skip rule derived cells in cellset
        :param csv_dialect: provide all csv output settings through standard library csv.Dialect
            If not provided dialect is created based on line_separator and value_separator arguments.
        :param line_separator:
        :param value_separator:
        :param sandbox_name: str
        :param use_iterative_json: use iterative json parsing to reduce memory consumption significantly.
        Comes at a cost of 3-5% performance.
        :param use_compact_json: bool
        :return: String
        """
        cellset_id = self.create_cellset_from_view(cube_name=cube_name, view_name=view_name, private=private,
                                                   sandbox_name=sandbox_name)
        if use_iterative_json:
            return self.extract_cellset_csv_iter_json(
                cellset_id=cellset_id, skip_zeros=skip_zeros, top=top, skip=skip,
                skip_consolidated_cells=skip_consolidated_cells,
                skip_rule_derived_cells=skip_rule_derived_cells, csv_dialect=csv_dialect,
                line_separator=line_separator, value_separator=value_separator,
                sandbox_name=sandbox_name, **kwargs)

        return self.extract_cellset_csv(
            cellset_id=cellset_id, skip_zeros=skip_zeros, top=top, skip=skip,
            skip_consolidated_cells=skip_consolidated_cells,
            skip_rule_derived_cells=skip_rule_derived_cells, csv_dialect=csv_dialect,
            line_separator=line_separator, value_separator=value_separator, sandbox_name=sandbox_name,
            use_compact_json=use_compact_json, **kwargs)

    def execute_mdx_elements_value_dict(self, mdx: str, top: int = None, skip: int = None, skip_zeros: bool = True,
                                        skip_consolidated_cells: bool = False, skip_rule_derived_cells: bool = False,
                                        element_separator: str = "|", sandbox_name: str = None,
                                        **kwargs) -> CaseAndSpaceInsensitiveDict:
        """ Optimized for performance. Get Dict from MDX Query.
        :param mdx: Valid MDX Query
        :param top: Int, number of cells to return (counting from top)
        :param skip: Int, number of cells to skip (counting from top)
        :param skip_zeros: skip zeros in cellset (irrespective of zero suppression in MDX / view)
        :param skip_consolidated_cells: skip consolidated cells in cellset
        :param skip_rule_derived_cells: skip rule derived cells in cellset
        :param element_separator: separator for the dimension element combination
        :param sandbox_name: str
        :return: CaseAndSpaceInsensitiveDict {'2020|Jan|Sales': 2000, '2020|Feb|Sales': 3000}
        """
        lines = self.execute_mdx_csv(mdx=mdx, top=top, skip=skip, skip_zeros=skip_zeros,
                                     skip_consolidated_cells=skip_consolidated_cells,
                                     skip_rule_derived_cells=skip_rule_derived_cells,
                                     value_separator=element_separator,
                                     sandbox_name=sandbox_name, **kwargs)
        elements_value_dict = CaseAndSpaceInsensitiveDict()
        for entries in lines.split("\r\n")[1:]:
            elements_value_dict[
                element_separator.join(entries.split(element_separator)[:-1])] = entries.split(element_separator)[-1]
        return elements_value_dict

    @require_pandas
    def execute_mdx_dataframe(self, mdx: str, top: int = None, skip: int = None, skip_zeros: bool = True,
                              skip_consolidated_cells: bool = False, skip_rule_derived_cells: bool = False,
                              sandbox_name: str = None, include_attributes: bool = False,
                              use_iterative_json: bool = False, use_compact_json: bool = False,
                              **kwargs) -> 'pd.DataFrame':
        """ Optimized for performance. Get Pandas DataFrame from MDX Query.

        Takes all arguments from the pandas.read_csv method:
        https://pandas.pydata.org/pandas-docs/stable/reference/api/pandas.read_csv.html

        :param mdx: Valid MDX Query
        :param top: Int, number of cells to return (counting from top)
        :param skip: Int, number of cells to skip (counting from top)
        :param skip_zeros: skip zeros in cellset (irrespective of zero suppression in MDX / view)
        :param skip_consolidated_cells: skip consolidated cells in cellset
        :param skip_rule_derived_cells: skip rule derived cells in cellset
        :param sandbox_name: str
        :param include_attributes: include attribute columns
        :param use_iterative_json: use iterative json parsing to reduce memory consumption significantly.
        Comes at a cost of 3-5% performance.
        :param use_compact_json: bool
        :return: Pandas Dataframe
        """
        cellset_id = self.create_cellset(mdx, sandbox_name=sandbox_name, **kwargs)
        return self.extract_cellset_dataframe(cellset_id, top=top, skip=skip, skip_zeros=skip_zeros,
                                              skip_consolidated_cells=skip_consolidated_cells,
                                              skip_rule_derived_cells=skip_rule_derived_cells,
                                              sandbox_name=sandbox_name, include_attributes=include_attributes,
                                              use_iterative_json=use_iterative_json, use_compact_json=use_compact_json,
                                              **kwargs)

    @require_pandas
    def execute_mdx_dataframe_shaped(self, mdx: str, sandbox_name: str = None, display_attribute: bool = False,
                                     **kwargs) -> 'pd.DataFrame':
        """ Retrieves data from cube in the shape of the query.
        Dimensions on rows can be stacked. One dimension must be placed on columns. Title selections are ignored.

        :param mdx:
        :param sandbox_name: str
        :param display_attribute: bool, show element name or first attribute from MDX PROPERTIES clause
        :param kwargs:
        :return:
        """
        cellset_id = self.create_cellset(mdx, sandbox_name=sandbox_name)
        return self.extract_cellset_dataframe_shaped(cellset_id, delete_cellset=True, sandbox_name=sandbox_name,
                                                     display_attribute=display_attribute, **kwargs)

    @require_pandas
    def execute_view_dataframe_shaped(self, cube_name: str, view_name: str, private: bool = False,
                                      sandbox_name: str = None,
                                      **kwargs) -> 'pd.DataFrame':
        """ Retrieves data from cube in the shape of the query.
        Dimensions on rows can be stacked. One dimension must be placed on columns. Title selections are ignored.

        :param cube_name:
        :param view_name:
        :param private:
        :param sandbox_name: str
        :param kwargs:
        :return:
        """
        cellset_id = self.create_cellset_from_view(cube_name, view_name, private, sandbox_name=sandbox_name)
        return self.extract_cellset_dataframe_shaped(cellset_id, delete_cellset=True, sandbox_name=sandbox_name,
                                                     **kwargs)

    @require_pandas
    def execute_view_dataframe_pivot(self, cube_name: str, view_name: str, private: bool = False, dropna: bool = False,
                                     fill_value: bool = None, sandbox_name: str = None, **kwargs) -> 'pd.DataFrame':
        """ Execute a cube view to get a pandas pivot dataframe, in the shape of the cube view

        :param cube_name: String, name of the cube
        :param view_name: String, name of the view
        :param private: True (private) or False (public)
        :param dropna:
        :param fill_value:
        :param sandbox_name: str
        :return:
        """
        cellset_id = self.create_cellset_from_view(cube_name=cube_name, view_name=view_name, private=private,
                                                   sandbox_name=sandbox_name, **kwargs)
        return self.extract_cellset_dataframe_pivot(
            cellset_id=cellset_id,
            dropna=dropna,
            fill_value=fill_value,
            sandbox_name=sandbox_name,
            **kwargs)

    @require_pandas
    def execute_mdx_dataframe_pivot(self, mdx: str, dropna: bool = False, fill_value: bool = None,
                                    sandbox_name: str = None) -> 'pd.DataFrame':
        """ Execute MDX Query to get a pandas pivot data frame in the shape as specified in the Query

        :param mdx:
        :param dropna:
        :param fill_value:
        :param sandbox_name: str
        :return:
        """
        cellset_id = self.create_cellset(mdx=mdx, sandbox_name=sandbox_name)
        return self.extract_cellset_dataframe_pivot(
            cellset_id=cellset_id,
            dropna=dropna,
            fill_value=fill_value,
            sandbox_name=sandbox_name)

    def execute_mdx_cellcount(self, mdx: str, sandbox_name: str = None, **kwargs) -> int:
        """ Execute MDX in order to understand how many cells are in a cellset.
        Only return number of cells in the cellset. FAST!

        :param mdx: MDX Query, as string
        :param sandbox_name: str
        :return: Number of Cells in the CellSet
        """
        cellset_id = self.create_cellset(mdx, sandbox_name=sandbox_name, **kwargs)
        return self.extract_cellset_cellcount(cellset_id, delete_cellset=True, sandbox_name=sandbox_name, **kwargs)

    def execute_view_elements_value_dict(self, cube_name: str, view_name: str, private: bool = False,
                                         top: int = None, skip: int = None, skip_zeros: bool = True,
                                         skip_consolidated_cells: bool = False, skip_rule_derived_cells: bool = False,
                                         element_separator: str = "|", sandbox_name: str = None,
                                         **kwargs) -> CaseAndSpaceInsensitiveDict:
        """ Optimized for performance. Get a Dict(tuple, value) from an existing Cube View
        Context dimensions are omitted in the resulting Dataframe !
        Cells with Zero/null are omitted by default, but still configurable!

        :param cube_name: String, name of the cube
        :param view_name: String, name of the view
        :param private: True (private) or False (public)
        :param top: Int, number of cells to return (counting from top)
        :param skip: Int, number of cells to skip (counting from top)
        :param skip_zeros: skip zeros in cellset (irrespective of zero suppression in MDX / view)
        :param skip_consolidated_cells: skip consolidated cells in cellset
        :param skip_rule_derived_cells: skip rule derived cells in cellset
        :param element_separator: separator for the dimension element combination
        :param sandbox_name: str
        :return: CaseAndSpaceInsensitiveDict {'2020|Jan|Sales': 2000, '2020|Feb|Sales': 3000}
        """
        lines = self.execute_view_csv(cube_name=cube_name, view_name=view_name, private=private, top=top, skip=skip,
                                      skip_zeros=skip_zeros, skip_consolidated_cells=skip_consolidated_cells,
                                      skip_rule_derived_cells=skip_rule_derived_cells,
                                      value_separator=element_separator, sandbox_name=sandbox_name, **kwargs)
        elements_value_dict = CaseAndSpaceInsensitiveDict()
        for entries in lines.split("\r\n")[1:]:
            elements_value_dict[
                element_separator.join(entries.split(element_separator)[:-1])] = entries.split(element_separator)[-1]
        return elements_value_dict

    @require_pandas
    def execute_view_dataframe(self, cube_name: str, view_name: str, private: bool = False, top: int = None,
                               skip: int = None, skip_zeros: bool = True, skip_consolidated_cells: bool = False,
                               skip_rule_derived_cells: bool = False, sandbox_name: str = None,
                               use_iterative_json: bool = False, **kwargs) -> 'pd.DataFrame':
        """ Optimized for performance. Get Pandas DataFrame from an existing Cube View
        Context dimensions are omitted in the resulting Dataframe !
        Cells with Zero/null are omitted !

        Takes all arguments from the pandas.read_csv method:
        https://pandas.pydata.org/pandas-docs/stable/reference/api/pandas.read_csv.html

        :param cube_name: String, name of the cube
        :param view_name: String, name of the view
        :param private: True (private) or False (public)
        :param top: Int, number of cells to return (counting from top)
        :param skip: Int, number of cells to skip (counting from top)
        :param skip_zeros: skip zeros in cellset (irrespective of zero suppression in MDX / view)
        :param skip_consolidated_cells: skip consolidated cells in cellset
        :param skip_rule_derived_cells: skip rule derived cells in cellset
        :param sandbox_name: str
        :param use_iterative_json: use iterative json parsing to reduce memory consumption significantly.
        Comes at a cost of 3-5% performance.
        :return: Pandas Dataframe
        """
        cellset_id = self.create_cellset_from_view(cube_name=cube_name, view_name=view_name, private=private,
                                                   sandbox_name=sandbox_name, **kwargs)
        return self.extract_cellset_dataframe(cellset_id, top=top, skip=skip, skip_zeros=skip_zeros,
                                              skip_consolidated_cells=skip_consolidated_cells,
                                              skip_rule_derived_cells=skip_rule_derived_cells,
                                              sandbox_name=sandbox_name, use_iterative_json=use_iterative_json,
                                              **kwargs)

    def execute_view_cellcount(self, cube_name: str, view_name: str, private: bool = False, sandbox_name: str = None,
                               **kwargs) -> int:
        """ Execute cube view in order to understand how many cells are in a cellset.
        Only return number of cells in the cellset. FAST!

        :param cube_name: String, name of the cube
        :param view_name: String, name of the view
        :param private: True (private) or False (public)
        :param sandbox_name: str
        :return:
        """
        cellset_id = self.create_cellset_from_view(cube_name=cube_name, view_name=view_name, private=private,
                                                   sandbox_name=sandbox_name, **kwargs)
        return self.extract_cellset_cellcount(cellset_id, delete_cellset=True, sandbox_name=sandbox_name, **kwargs)

    def execute_mdx_rows_and_values_string_set(
            self,
            mdx: str,
            exclude_empty_cells: bool = True,
            sandbox_name: str = None,
            **kwargs) -> CaseAndSpaceInsensitiveSet:
        """ Retrieve row element names and **string** cell values in a case and space insensitive set

        :param exclude_empty_cells:
        :param mdx:
        :param sandbox_name: str
        :return:
        """
        rows_and_values = self.execute_mdx_rows_and_values(mdx, element_unique_names=False, sandbox_name=sandbox_name,
                                                           **kwargs)
        return self._extract_string_set_from_rows_and_values(rows_and_values, exclude_empty_cells)

    def execute_view_rows_and_values_string_set(self, cube_name: str, view_name: str, private: bool = False,
                                                exclude_empty_cells: bool = True, sandbox_name: str = None,
                                                **kwargs) -> CaseAndSpaceInsensitiveSet:
        """ Retrieve row element names and **string** cell values in a case and space insensitive set

        :param cube_name: String, name of the cube
        :param view_name: String, name of the view
        :param private: True (private) or False (public)
        :param exclude_empty_cells:
        :param sandbox_name: str
        :return:
        """
        rows_and_values = self.execute_view_rows_and_values(cube_name, view_name, private, False,
                                                            sandbox_name=sandbox_name, **kwargs)
        return self._extract_string_set_from_rows_and_values(rows_and_values, exclude_empty_cells)

    def execute_mdx_ui_dygraph(
            self,
            mdx: str,
            elem_properties: Iterable[str] = None,
            member_properties: Iterable[str] = None,
            value_precision: int = 2,
            top: int = None,
            skip: int = None,
            sandbox_name: str = None,
            use_compact_json: bool = False,
            **kwargs) -> Dict:
        """ Execute MDX get dygraph dictionary
        Useful for grids or charting libraries that want an array of cell values per column
        Returns 3-dimensional cell structure for tabbed grids or multiple charts
        Example 'cells' return format:
            'cells': {
                '10100': [
                    ['Q1-2004', 28981046.50724231, 19832724.72429739],
                    ['Q2-2004', 29512482.207418434, 20365654.788303416],
                    ['Q3-2004', 29913730.038971487, 20729201.329183243],
                    ['Q4-2004', 29563345.9542385, 20480205.20121749]],
                '10200': [
                    ['Q1-2004', 13888143.710000003, 9853293.623709997],
                    ['Q2-2004', 14300216.43, 10277650.763958748],
                    ['Q3-2004', 14502421.63, 10466934.096533755],
                    ['Q4-2004', 14321501.940000001, 10333095.839474997]]
            },
        :param top: Int, number of cells to return (counting from top)
        :param skip: Int, number of cells to skip (counting from top)
        :param mdx: String, valid MDX Query
        :param elem_properties: List of properties to be queried from the elements. E.g. ['UniqueName','Attributes']
        :param member_properties: List of properties to be queried from the members. E.g. ['UniqueName','Attributes']
        :param value_precision: Integer (optional) specifying number of decimal places to return
        :param sandbox_name: str
        :param use_compact_json: bool
        :return: dict: { titles: [], headers: [axis][], cells: { Page0: [ [column name, column values], [], ... ], ...}}
        """
        cellset_id = self.create_cellset(mdx=mdx, sandbox_name=sandbox_name)
        data = self.extract_cellset_raw(cellset_id=cellset_id,
                                        cell_properties=["Value"],
                                        elem_properties=elem_properties,
                                        member_properties=list(set(member_properties or []) | {"Name"}),
                                        top=top,
                                        skip=skip,
                                        delete_cellset=True,
                                        sandbox_name=sandbox_name,
                                        use_compact_json=use_compact_json,
                                        **kwargs)
        return Utils.build_ui_dygraph_arrays_from_cellset(raw_cellset_as_dict=data, value_precision=value_precision)

    def execute_view_ui_dygraph(
            self,
            cube_name: str,
            view_name: str,
            private: bool = False,
            elem_properties: Iterable[str] = None,
            member_properties: Iterable[str] = None,
            value_precision: int = 2,
            top: int = None,
            skip: int = None,
            sandbox_name: str = None,
            use_compact_json: bool = False,
            **kwargs):
        """
        Useful for grids or charting libraries that want an array of cell values per row.
        Returns 3-dimensional cell structure for tabbed grids or multiple charts.
        Rows and pages are dicts, addressable by their name. Proper order of rows can be obtained in headers[1]
        Example 'cells' return format:
            'cells': {
                '10100': {
                    'Net Operating Income': [ 19832724.72429739,
                                              20365654.788303416,
                                              20729201.329183243,
                                              20480205.20121749],
                    'Revenue': [ 28981046.50724231,
                                 29512482.207418434,
                                 29913730.038971487,
                                 29563345.9542385]},
                '10200': {
                    'Net Operating Income': [ 9853293.623709997,
                                               10277650.763958748,
                                               10466934.096533755,
                                               10333095.839474997],
                    'Revenue': [ 13888143.710000003,
                                 14300216.43,
                                 14502421.63,
                                 14321501.940000001]}
            },

        :param top: Int, number of cells to return (counting from top)
        :param skip: Int, number of cells to skip (counting from top)
        :param cube_name: cube name
        :param view_name: view name
        :param private: True (private) or False (public)
        :param elem_properties: List of properties to be queried from the elements. E.g. ['UniqueName','Attributes']
        :param member_properties: List of properties to be queried from the members. E.g. ['UniqueName','Attributes']
        :param value_precision: Integer (optional) specifying number of decimal places to return
        :param sandbox_name: str
        :param use_compact_json: bool
        :return:
        """
        cellset_id = self.create_cellset_from_view(cube_name=cube_name, view_name=view_name, private=private,
                                                   sandbox_name=sandbox_name, **kwargs)
        data = self.extract_cellset_raw(cellset_id=cellset_id,
                                        cell_properties=["Value"],
                                        elem_properties=elem_properties,
                                        member_properties=list(set(member_properties or []) | {"Name"}),
                                        top=top,
                                        skip=skip,
                                        delete_cellset=True,
                                        sandbox_name=sandbox_name,
                                        use_compact_json=use_compact_json,
                                        **kwargs)
        return Utils.build_ui_dygraph_arrays_from_cellset(raw_cellset_as_dict=data, value_precision=value_precision)

    def execute_mdx_ui_array(
            self,
            mdx: str,
            elem_properties: Iterable[str] = None,
            member_properties: Iterable[str] = None,
            value_precision: int = 2,
            top: int = None,
            skip: int = None,
            sandbox_name: str = None,
            use_compact_json: bool = False,
            **kwargs):
        """
        Useful for grids or charting libraries that want an array of cell values per row.
        Returns 3-dimensional cell structure for tabbed grids or multiple charts.
        Rows and pages are dicts, addressable by their name. Proper order of rows can be obtained in headers[1]
        Example 'cells' return format:
            'cells': {
                '10100': {
                    'Net Operating Income': [ 19832724.72429739,
                                              20365654.788303416,
                                              20729201.329183243,
                                              20480205.20121749],
                    'Revenue': [ 28981046.50724231,
                                 29512482.207418434,
                                 29913730.038971487,
                                 29563345.9542385]},
                '10200': {
                    'Net Operating Income': [ 9853293.623709997,
                                               10277650.763958748,
                                               10466934.096533755,
                                               10333095.839474997],
                    'Revenue': [ 13888143.710000003,
                                 14300216.43,
                                 14502421.63,
                                 14321501.940000001]}
            },

        :param top: Int, number of cells to return (counting from top)
        :param skip: Int, number of cells to skip (counting from top)
        :param mdx: a valid MDX Query
        :param elem_properties: List of properties to be queried from the elements. E.g. ['UniqueName','Attributes']
        :param member_properties: List of properties to be queried from the members. E.g. ['UniqueName','Attributes']
        :param value_precision: Integer (optional) specifying number of decimal places to return
        :param sandbox_name: str
        :param use_compact_json: bool
        :return: dict :{ titles: [], headers: [axis][], cells:{ Page0:{ Row0:{ [row values], Row1: [], ...}, ...}, ...}}
        """
        cellset_id = self.create_cellset(mdx=mdx, sandbox_name=sandbox_name, **kwargs)
        data = self.extract_cellset_raw(cellset_id=cellset_id,
                                        cell_properties=["Value"],
                                        elem_properties=elem_properties,
                                        member_properties=list(set(member_properties or []) | {"Name"}),
                                        top=top,
                                        skip=skip,
                                        delete_cellset=True,
                                        sandbox_name=sandbox_name,
                                        use_compact_json=use_compact_json,
                                        **kwargs)
        return Utils.build_ui_arrays_from_cellset(raw_cellset_as_dict=data, value_precision=value_precision)

    def execute_view_ui_array(
            self,
            cube_name: str,
            view_name: str,
            private: bool = False,
            elem_properties: Iterable[str] = None,
            member_properties: Iterable[str] = None,
            value_precision: int = 2,
            top: int = None,
            skip: int = None,
            sandbox_name: str = None,
            use_compact_json: bool = False,
            **kwargs):
        """
        Useful for grids or charting libraries that want an array of cell values per row.
        Returns 3-dimensional cell structure for tabbed grids or multiple charts.
        Rows and pages are dicts, addressable by their name. Proper order of rows can be obtained in headers[1]
        Example 'cells' return format:
            'cells': {
                '10100': {
                    'Net Operating Income': [ 19832724.72429739,
                                              20365654.788303416,
                                              20729201.329183243,
                                              20480205.20121749],
                    'Revenue': [ 28981046.50724231,
                                 29512482.207418434,
                                 29913730.038971487,
                                 29563345.9542385]},
                '10200': {
                    'Net Operating Income': [ 9853293.623709997,
                                               10277650.763958748,
                                               10466934.096533755,
                                               10333095.839474997],
                    'Revenue': [ 13888143.710000003,
                                 14300216.43,
                                 14502421.63,
                                 14321501.940000001]}
            },

        :param top: Int, number of cells to return (counting from top)
        :param skip: Int, number of cells to skip (counting from top)
        :param cube_name: String, name of the cube
        :param view_name: String, name of the view
        :param private: True (private) or False (public)
        :param elem_properties: List of properties to be queried from the elements. E.g. ['UniqueName','Attributes']
        :param member_properties: List properties to be queried from the member. E.g. ['Name', 'UniqueName']
        :param value_precision: Integer (optional) specifying number of decimal places to return
        :param sandbox_name: str
        :param use_compact_json: bool
        :return: dict :{ titles: [], headers: [axis][], cells:{ Page0:{ Row0: {[row values], Row1: [], ...}, ...}, ...}}
        """
        cellset_id = self.create_cellset_from_view(cube_name=cube_name, view_name=view_name, private=private,
                                                   sandbox_name=sandbox_name, **kwargs)
        data = self.extract_cellset_raw(cellset_id=cellset_id,
                                        cell_properties=["Value"],
                                        elem_properties=elem_properties,
                                        member_properties=list(set(member_properties or []) | {"Name"}),
                                        top=top,
                                        skip=skip,
                                        delete_cellset=True,
                                        sandbox_name=sandbox_name,
                                        use_compact_json=use_compact_json,
                                        **kwargs)
        return Utils.build_ui_arrays_from_cellset(raw_cellset_as_dict=data, value_precision=value_precision)

    def extract_cellset_raw_response(
            self,
            cellset_id: str,
            cell_properties: Iterable[str] = None,
            elem_properties: Iterable[str] = None,
            member_properties: Iterable[str] = None,
            top: int = None,
            skip: int = None,
            skip_contexts: bool = False,
            skip_zeros: bool = False,
            skip_consolidated_cells: bool = False,
            skip_rule_derived_cells: bool = False,
            sandbox_name: str = None,
            include_hierarchies: bool = False,
            **kwargs) -> Response:
        """ Extract full cellset data and return the raw data from TM1

        :param cellset_id: String; ID of existing cellset
        :param cell_properties: List of properties to be queried from cells. E.g. ['Value', 'RuleDerived', ...]
        :param elem_properties: List of properties to be queried from elements. E.g. ['UniqueName','Attributes', ...]
        :param member_properties: List properties to be queried from the member. E.g. ['Name', 'UniqueName']
        :param top: Integer limiting the number of cells and the number or rows returned
        :param skip: Integer limiting the number of cells and the number or rows returned
        :param skip_contexts:
        :param skip_zeros: skip zeros in cellset (irrespective of zero suppression in MDX / view)
        :param skip_consolidated_cells: skip consolidated cells in cellset
        :param skip_rule_derived_cells: skip rule derived cells in cellset
        :param sandbox_name: str
        :param include_hierarchies: retrieve Hierarchies property on Axes
        :return: Raw format from TM1.
        """
        if not cell_properties:
            cell_properties = ['Value']

        if skip_rule_derived_cells:
            cell_properties.append("RuleDerived")
            # necessary due to bug in TM1 11.8: If only RuleDerived is retrieved it occasionally produces wrong results
            cell_properties.append("Updateable")

        if skip_consolidated_cells:
            cell_properties.append("Consolidated")

        if skip or skip_zeros or skip_rule_derived_cells or skip_consolidated_cells:
            if 'Ordinal' not in cell_properties:
                cell_properties.append('Ordinal')

        # select Name property if member_properties is None or empty.
        # Necessary, as tm1 default behaviour is to return all properties if no $select is specified in the request.
        if member_properties is None or len(list(member_properties)) == 0:
            member_properties = ["Name"]
        select_member_properties = "$select={}".format(",".join(member_properties))

        expand_elem_properties = ";$expand=Element($select={elem_properties})".format(
            elem_properties=",".join(elem_properties)) \
            if elem_properties is not None and len(list(elem_properties)) > 0 \
            else ""

        filter_axis = "$filter=Ordinal ne 2;" if skip_contexts else ""

        filter_cells = ""
        if skip_zeros or skip_consolidated_cells or skip_rule_derived_cells:
            filters = []
            if skip_zeros:
                filters.append("Value ne 0 and Value ne null and Value ne ''")
            if skip_consolidated_cells:
                filters.append("Consolidated eq false")
            if skip_rule_derived_cells:
                filters.append("RuleDerived eq false")

            filter_cells = " and ".join(filters)

        if include_hierarchies:
            expand_hierarchies = "Hierarchies($select=Name;$expand=Dimension($select=Name)),"
        else:
            expand_hierarchies = ""

        url = "/api/v1/Cellsets('{cellset_id}')?$expand=" \
              "Cube($select=Name;$expand=Dimensions($select=Name))," \
              "Axes({filter_axis}$expand={hierarchies}Tuples($expand=Members({select_member_properties}" \
              "{expand_elem_properties}{top_rows})))," \
              "Cells($select={cell_properties}{top_cells}{skip_cells}{filter_cells})" \
            .format(cellset_id=cellset_id,
                    top_rows=f";$top={top}" if top and not skip else "",
                    cell_properties=",".join(cell_properties),
                    filter_axis=filter_axis,
                    hierarchies=expand_hierarchies,
                    select_member_properties=select_member_properties,
                    expand_elem_properties=expand_elem_properties,
                    top_cells=f";$top={top}" if top else "",
                    skip_cells=f";$skip={skip}" if skip else "",
                    filter_cells=f";$filter={filter_cells}" if filter_cells else "")
        url = add_url_parameters(url, **{"!sandbox": sandbox_name})
        response = self._rest.GET(url=url, **kwargs)
        return response

    @tidy_cellset
    def extract_cellset_raw(
            self,
            cellset_id: str,
            cell_properties: Iterable[str] = None,
            elem_properties: Iterable[str] = None,
            member_properties: Iterable[str] = None,
            top: int = None,
            skip: int = None,
            skip_contexts: bool = False,
            skip_zeros: bool = False,
            skip_consolidated_cells: bool = False,
            skip_rule_derived_cells: bool = False,
            sandbox_name: str = None,
            include_hierarchies: bool = False,
            use_compact_json: bool = False,
            **kwargs) -> Dict:
        """ Extract full cellset data and return the raw data from TM1

        :param cellset_id: String; ID of existing cellset
        :param cell_properties: List of properties to be queried from cells. E.g. ['Value', 'RuleDerived', ...]
        :param elem_properties: List of properties to be queried from elements. E.g. ['UniqueName','Attributes', ...]
        :param member_properties: List properties to be queried from the member. E.g. ['Name', 'UniqueName']
        :param top: Integer limiting the number of cells and the number or rows returned
        :param skip: Integer limiting the number of cells and the number or rows returned
        :param skip_contexts:
        :param skip_zeros: skip zeros in cellset (irrespective of zero suppression in MDX / view)
        :param skip_consolidated_cells: skip consolidated cells in cellset
        :param skip_rule_derived_cells: skip rule derived cells in cellset
        :param sandbox_name: str
        :param include_hierarchies: retrieve Hierarchies property on Axes
        :param use_compact_json: bool
        :return: Raw format from TM1.
        """
        if not use_compact_json:
            cellset_response = self.extract_cellset_raw_response(
                cellset_id,
                cell_properties,
                elem_properties,
                member_properties,
                top,
                skip,
                skip_contexts,
                skip_zeros,
                skip_consolidated_cells,
                skip_rule_derived_cells,
                sandbox_name,
                include_hierarchies,
                **kwargs)

            return cellset_response.json()

        metadata = self.extract_cellset_metadata_raw(cellset_id=cellset_id,
                                                     elem_properties=elem_properties,
                                                     member_properties=member_properties,
                                                     top=top,
                                                     skip=skip,
                                                     skip_contexts=skip_contexts,
                                                     include_hierarchies=include_hierarchies,
                                                     sandbox_name=sandbox_name,
                                                     **kwargs)
        cells = self.extract_cellset_cells_raw(cellset_id=cellset_id,
                                               cell_properties=cell_properties,
                                               top=top,
                                               skip=skip,
                                               skip_zeros=skip_zeros,
                                               skip_consolidated_cells=skip_consolidated_cells,
                                               skip_rule_derived_cells=skip_rule_derived_cells,
                                               sandbox_name=sandbox_name,
                                               use_compact_json=use_compact_json,
                                               **kwargs)

        # Combine metadata and cells back into a single object
        return {**metadata, **cells}

    def extract_cellset_metadata_raw(
            self,
            cellset_id: str,
            elem_properties: Iterable[str] = None,
            member_properties: Iterable[str] = None,
            top: int = None,
            skip: int = None,
            skip_contexts: bool = False,
            include_hierarchies: bool = False,
            sandbox_name: str = None,
            **kwargs):

        # select Name property if member_properties is None or empty.
        # Necessary, as tm1 default behaviour is to return all properties if no $select is specified in the request.
        if member_properties is None or len(list(member_properties)) == 0:
            member_properties = ["Name"]
        select_member_properties = "$select={}".format(",".join(member_properties))

        expand_elem_properties = ";$expand=Element($select={elem_properties})".format(
            elem_properties=",".join(elem_properties)) \
            if elem_properties is not None and len(list(elem_properties)) > 0 \
            else ""

        if include_hierarchies:
            expand_hierarchies = "Hierarchies($select=Name;$expand=Dimension($select=Name)),"
        else:
            expand_hierarchies = ""

        filter_axis = "$filter=Ordinal ne 2;" if skip_contexts else ""

        url = "/api/v1/Cellsets('{cellset_id}')?$expand=" \
              "Cube($select=Name;$expand=Dimensions($select=Name))," \
              "Axes({filter_axis}$expand={hierarchies}Tuples($expand=Members({select_member_properties}" \
              "{expand_elem_properties}{top_rows})))" \
            .format(cellset_id=cellset_id,
                    top_rows=f";$top={top}" if top and not skip else "",
                    filter_axis=filter_axis,
                    hierarchies=expand_hierarchies,
                    select_member_properties=select_member_properties,
                    expand_elem_properties=expand_elem_properties)

        url = add_url_parameters(url, **{"!sandbox": sandbox_name})
        response = self._rest.GET(url=url, **kwargs)
        return response.json()

    @odata_compact_json(return_as_dict=True)
    def extract_cellset_cells_raw(
            self, cellset_id: str,
            cell_properties: Iterable[str] = None,
            top: int = None,
            skip: int = None,
            skip_zeros: bool = False,
            skip_consolidated_cells: bool = False,
            skip_rule_derived_cells: bool = False,
            sandbox_name: str = None,
            **kwargs):

        if not cell_properties:
            cell_properties = ['Value']

        if skip_rule_derived_cells:
            cell_properties.append("RuleDerived")
            # necessary due to bug in TM1 11.8: If only RuleDerived is retrieved it occasionally produces wrong results
            cell_properties.append("Updateable")

        if skip_consolidated_cells:
            cell_properties.append("Consolidated")

        if skip or skip_zeros or skip_rule_derived_cells or skip_consolidated_cells:
            if 'Ordinal' not in cell_properties:
                cell_properties.append('Ordinal')

        filter_cells = ""
        if skip_zeros or skip_consolidated_cells or skip_rule_derived_cells:
            filters = []
            if skip_zeros:
                filters.append("Value ne 0 and Value ne null and Value ne ''")
            if skip_consolidated_cells:
                filters.append("Consolidated eq false")
            if skip_rule_derived_cells:
                filters.append("RuleDerived eq false")

            filter_cells = " and ".join(filters)

        url = "/api/v1/Cellsets('{cellset_id}')?$expand=" \
              "Cells($select={cell_properties}{top_cells}{skip_cells}{filter_cells})" \
            .format(cellset_id=cellset_id,
                    cell_properties=",".join(cell_properties),
                    top_cells=f";$top={top}" if top else "",
                    skip_cells=f";$skip={skip}" if skip else "",
                    filter_cells=f";$filter={filter_cells}" if filter_cells else "")

        url = add_url_parameters(url, **{"!sandbox": sandbox_name})
        response = self._rest.GET(url=url, **kwargs)
        return response.json()

    @tidy_cellset
    @odata_compact_json(return_as_dict=False)
    def extract_cellset_values(self, cellset_id: str, sandbox_name: str = None, use_compact_json: bool = False,
                               skip_zeros: bool = False, skip_consolidated_cells: bool = False,
                               skip_rule_derived_cells: bool = False, **kwargs) -> List[Union[str, float]]:
        """ Extract cellset data and return only the cells and values

        :param cellset_id: String; ID of existing cellset
        :param sandbox_name: str
        :param use_compact_json: bool
        :param skip_zeros: bool
        :param skip_consolidated_cells: bool
        :param skip_rule_derived_cells: bool
        :return: Raw format from TM1.
        """

        filter_cells = ""
        if skip_zeros or skip_consolidated_cells or skip_rule_derived_cells:
            filters = []
            if skip_zeros:
                filters.append("Value ne 0 and Value ne null and Value ne ''")
            if skip_consolidated_cells:
                filters.append("Consolidated eq false")
            if skip_rule_derived_cells:
                filters.append("RuleDerived eq false")

            filter_cells = " and ".join(filters)

        url = format_url(
            "/api/v1/Cellsets('{}')?$expand=Cells($select=Value{})",
            cellset_id,
            f";$filter={filter_cells}" if filter_cells else "")
        url = add_url_parameters(url, **{"!sandbox": sandbox_name})
        response = self._rest.GET(url=url, **kwargs)

        if not use_compact_json:
            return [cell["Value"] for cell in response.json()["Cells"]]

        return response.json()

    @tidy_cellset
    def extract_cellset_rows_and_values(self, cellset_id: str, element_unique_names: bool = True,
                                        sandbox_name: str = None,
                                        **kwargs) -> CaseAndSpaceInsensitiveTuplesDict:
        """ Retrieve row element names and values in a case and space insensitive dictionary

        :param cellset_id:
        :param element_unique_names:
        :param kwargs:
        :param sandbox_name: str
        :return:
        """
        url = "/api/v1/Cellsets('{}')?$expand=" \
              "Axes($filter=Ordinal eq 1;$expand=Tuples(" \
              "$expand=Members($select=Element;$expand=Element($select={}))))," \
              "Cells($select=Value)".format(cellset_id, "UniqueName" if element_unique_names else "Name")
        url = add_url_parameters(url, **{"!sandbox": sandbox_name})
        response = self._rest.GET(url=url, **kwargs)
        response_json = response.json()
        rows = response_json["Axes"][0]["Tuples"]
        cell_values = [cell["Value"] for cell in response_json["Cells"]]

        result = CaseAndSpaceInsensitiveTuplesDict()

        number_rows = len(rows)
        # avoid division by zero
        if not number_rows:
            return result
        number_cells = len(cell_values)
        number_columns = int(number_cells / number_rows)

        cell_values_by_row = [cell_values[cell_counter:cell_counter + number_columns]
                              for cell_counter
                              in range(0, number_cells, number_columns)]
        element_names_by_row = [tuple(member["Element"]["UniqueName" if element_unique_names else "Name"]
                                      for member
                                      in tupl["Members"])
                                for tupl
                                in rows]
        for element_tuple, cells in zip(element_names_by_row, cell_values_by_row):
            result[element_tuple] = cells
        return result

    @tidy_cellset
    def extract_cellset_composition(self, cellset_id: str, sandbox_name: str = None, **kwargs):
        """ Retrieve composition of dimensions on the axes in the cellset

        :param cellset_id:
        :param kwargs:
        :param sandbox_name: str
        :return:
        """
        url = "/api/v1/Cellsets('{}')?$expand=" \
              "Cube($select=Name)," \
              "Axes($expand=Hierarchies($select=UniqueName))".format(cellset_id)
        url = add_url_parameters(url, **{"!sandbox": sandbox_name})
        response = self._rest.GET(url=url, **kwargs)
        response_json = response.json()
        cube = response_json["Cube"]["Name"]

        rows, titles, columns = [], [], []
        if len(response_json["Axes"]) == 1:
            if response_json["Axes"][0]["Hierarchies"]:
                columns = [hierarchy["UniqueName"] for hierarchy in response_json["Axes"][0]["Hierarchies"]]
        else:
            if response_json["Axes"][0]["Hierarchies"]:
                columns = [hierarchy["UniqueName"] for hierarchy in response_json["Axes"][0]["Hierarchies"]]
            if response_json["Axes"][1]["Hierarchies"]:
                rows = [hierarchy["UniqueName"] for hierarchy in response_json["Axes"][1]["Hierarchies"]]
        if len(response_json["Axes"]) > 2:
            titles = [hierarchy["UniqueName"] for hierarchy in response_json["Axes"][2]["Hierarchies"]]
        return cube, titles, rows, columns

    @tidy_cellset
    def extract_cellset_cellcount(self, cellset_id: str, sandbox_name: str = None, **kwargs) -> int:
        """ Retrieve number of cells in the cellset

        :param cellset_id:
        :param sandbox_name: str
        :param kwargs:
        :return:
        """
        url = "/api/v1/Cellsets('{}')/Cells/$count".format(cellset_id)
        url = add_url_parameters(url, **{"!sandbox": sandbox_name})
        response = self._rest.GET(url, **kwargs)
        return int(response.content)

    def extract_cellset_csv(
            self,
            cellset_id: str,
            top: int = None,
            skip: int = None,
            skip_zeros: bool = True,
            skip_consolidated_cells: bool = False,
            skip_rule_derived_cells: bool = False,
            csv_dialect: 'csv.Dialect' = None,
            line_separator: str = "\r\n",
            value_separator: str = ",",
            sandbox_name: str = None,
            include_attributes: bool = False,
            use_compact_json: bool = False,
            **kwargs) -> str:
        """ Execute cellset and return only the 'Content', in csv format

        :param cellset_id: String; ID of existing cellset
        :param top: Int, number of cells to return (counting from top)
        :param skip: Int, number of cells to skip (counting from top)
        :param skip_zeros: skip zeros in cellset (irrespective of zero suppression in MDX / view)
        :param skip_consolidated_cells: skip consolidated cells in cellset
        :param skip_rule_derived_cells: skip rule derived cells in cellset
        :param csv_dialect: provide all csv output settings through standard library csv.Dialect
            If not provided dialect is created based on line_separator and value_separator arguments.
        :param line_separator:
        :param value_separator
        :param sandbox_name: str
        :param include_attributes: include attribute columns
        :param use_compact_json: bool
        :return: Raw format from TM1.
        """
        _, _, rows, columns = self.extract_cellset_composition(cellset_id, delete_cellset=False,
                                                               sandbox_name=sandbox_name, **kwargs)
        cellset_dict = self.extract_cellset_raw(cellset_id, cell_properties=["Value"], top=top, skip=skip,
                                                skip_contexts=True, skip_zeros=skip_zeros,
                                                skip_consolidated_cells=skip_consolidated_cells,
                                                skip_rule_derived_cells=skip_rule_derived_cells,
                                                delete_cellset=True, sandbox_name=sandbox_name,
                                                elem_properties=['Name'],
                                                member_properties=['Name',
                                                                   'Attributes'] if include_attributes else None,
                                                use_compact_json=use_compact_json,
                                                **kwargs)
        return build_csv_from_cellset_dict(rows, columns, cellset_dict, csv_dialect=csv_dialect,
                                           line_separator=line_separator, value_separator=value_separator,
                                           top=top, include_attributes=include_attributes)

    def extract_cellset_csv_iter_json(
            self,
            cellset_id: str,
            top: int = None,
            skip: int = None,
            skip_zeros: bool = True,
            skip_consolidated_cells: bool = False,
            skip_rule_derived_cells: bool = False,
            csv_dialect: 'csv.Dialect' = None,
            line_separator: str = "\r\n",
            value_separator: str = ",",
            sandbox_name: str = None,
            include_attributes: bool = False,
            **kwargs) -> str:
        """ Execute cellset and return only the 'Content', in csv format

        :param cellset_id: String; ID of existing cellset
        :param top: Int, number of cells to return (counting from top)
        :param skip: Int, number of cells to skip (counting from top)
        :param skip_zeros: skip zeros in cellset (irrespective of zero suppression in MDX / view)
        :param skip_consolidated_cells: skip consolidated cells in cellset
        :param skip_rule_derived_cells: skip rule derived cells in cellset
        :param csv_dialect: provide all csv output settings through standard library csv.Dialect
            If not provided dialect is created based on line_separator and value_separator arguments.
        :param line_separator:
        :param value_separator
        :param sandbox_name: str
        :param include_attributes: boolean
        :return: Raw format from TM1.
        """
        cube, _, rows, columns = self.extract_cellset_composition(
            cellset_id,
            delete_cellset=False,
            sandbox_name=sandbox_name,
            **kwargs)

        cellset_response = self.extract_cellset_raw_response(
            cellset_id, cell_properties=["Value"], top=top, skip=skip,
            skip_contexts=True, skip_zeros=skip_zeros,
            skip_consolidated_cells=skip_consolidated_cells,
            skip_rule_derived_cells=skip_rule_derived_cells,
            delete_cellset=True,
            sandbox_name=sandbox_name,
            member_properties=['Name', 'Attributes'] if include_attributes else ['Name'],
            **kwargs)

        row_headers = list(dimension_names_from_element_unique_names(rows))
        column_headers = list(dimension_names_from_element_unique_names(columns))

        if csv_dialect is None:
            csv.register_dialect("TM1py", delimiter=value_separator, lineterminator=line_separator)
            csv_dialect = csv.get_dialect("TM1py")

        # start parsing of JSON directly into CSV
        axes0_list = []
        axes1_list = []
        current_axes = 0
        current_tuple = 0
        current_cell_ordinal = 0
        csv_body = StringIO()
        csv_writer = csv.writer(csv_body, dialect=csv_dialect)

        parser = ijson.parse(cellset_response.content)
        prefixes_of_interest = ['Cells.item.Value', 'Axes.item.Tuples.item.Members.item.Name',
                                'Cells.item.Ordinal', 'Axes.item.Tuples.item.Ordinal', 'Cube.Dimensions.item.Name',
                                'Axes.item.Ordinal']

        attributes_prefixes = set()
        if include_attributes:
            attributes_by_dimension = self._get_attributes_by_dimension(cube)
            for _, attributes in attributes_by_dimension.items():
                for attribute in attributes:
                    prefix = f'Axes.item.Tuples.item.Members.item.Attributes.{attribute}'
                    prefixes_of_interest.append(prefix)
                    attributes_prefixes.add(prefix)

        gen = ((prefix, event, value) for prefix, event, value in parser if prefix in prefixes_of_interest)
        for prefix, event, value in gen:
            if prefix == 'Cells.item.Value':
                q, r = divmod(current_cell_ordinal, len(axes0_list))
                axes0_index = r
                axes1_index = q
                if len(axes0_list) == 1 and len(axes0_list[0]) == 0:
                    csv_writer.writerow(axes1_list[axes1_index] + [str(value)])
                # case of no row selection
                elif len(axes1_list) == 0:
                    csv_writer.writerow(axes0_list[axes0_index] + [str(value)])
                else:
                    csv_writer.writerow(axes1_list[axes1_index] + axes0_list[axes0_index] + [str(value)])

            elif (prefix, event) == ('Axes.item.Tuples.item.Members.item.Name', 'string'):
                if current_axes == 0:
                    axes0_list[current_tuple].append(value)
                else:
                    axes1_list[current_tuple].append(value)

            if prefix in attributes_prefixes:
                if event not in ('string', 'number'):
                    continue

                attribute_name = prefix.split('.')[-1]
                value = str(value)

                if current_axes == 0:
                    axes0_list[current_tuple].append(value)
                else:
                    axes1_list[current_tuple].append(value)

                # Add header entry for attribute if necessary
                if current_tuple == 0:
                    if current_axes == 0:
                        column_headers.insert(len(axes0_list[current_tuple]) - 1, attribute_name)
                    else:
                        row_headers.insert(len(axes1_list[current_tuple]) - 1, attribute_name)

            elif (prefix, event) == ('Cells.item.Ordinal', 'number'):
                current_cell_ordinal = value

            elif (prefix, event) == ('Axes.item.Tuples.item.Ordinal', 'number'):
                current_tuple = value
                if current_axes == 0:
                    axes0_list.append(list())
                else:
                    axes1_list.append(list())

            elif (prefix, event) == ('Axes.item.Ordinal', 'number'):
                current_axes = value

        # comply with prior implementations: return empty string when cellset is empty
        if csv_body.getvalue() == "":
            return ""

        # prepare header
        csv_header = StringIO()
        csv_header_writer = csv.writer(csv_header, dialect=csv_dialect)
        csv_header_writer.writerow(row_headers + column_headers + ['Value'])

        cellset_response.close()
        return csv_header.getvalue() + csv_body.getvalue().strip()

    @require_pandas
    def extract_cellset_dataframe(
            self,
            cellset_id: str,
            top: int = None,
            skip: int = None,
            skip_zeros: bool = True,
            skip_consolidated_cells: bool = False,
            skip_rule_derived_cells: bool = False,
            sandbox_name: str = None,
            include_attributes: bool = False,
            use_iterative_json: bool = False,
            use_compact_json: bool = False,
            **kwargs) -> 'pd.DataFrame':
        """ Build pandas data frame from cellset_id

        :param cellset_id:
        :param top: Int, number of cells to return (counting from top)
        :param skip: Int, number of cells to skip (counting from top)
        :param skip_zeros: skip zeros in cellset (irrespective of zero suppression in MDX / view)
        :param skip_consolidated_cells: skip consolidated cells in cellset
        :param skip_rule_derived_cells: skip rule derived cells in cellset
        :param sandbox_name: str
        :param include_attributes: include attribute columns
        :param use_iterative_json: use iterative json parsing to reduce memory consumption significantly.
        Comes at a cost of 3-5% performance.
        :param use_compact_json: bool
        :param kwargs:
        :return:
        """
        if use_iterative_json and use_compact_json:
            raise ValueError("Iterative JSON parsing must not be used together with compact JSON")

        if use_iterative_json:
            raw_csv = self.extract_cellset_csv_iter_json(
                cellset_id=cellset_id, top=top, skip=skip, skip_zeros=skip_zeros,
                skip_rule_derived_cells=skip_rule_derived_cells, skip_consolidated_cells=skip_consolidated_cells,
                value_separator='~', sandbox_name=sandbox_name, include_attributes=include_attributes, **kwargs)
        else:
            raw_csv = self.extract_cellset_csv(
                cellset_id=cellset_id, top=top, skip=skip, skip_zeros=skip_zeros,
                skip_rule_derived_cells=skip_rule_derived_cells, skip_consolidated_cells=skip_consolidated_cells,
                value_separator='~', sandbox_name=sandbox_name, include_attributes=include_attributes,
                use_compact_json=use_compact_json, **kwargs)

        if not raw_csv:
            return pd.DataFrame()

        memory_file = StringIO(raw_csv)
        # make sure all element names are strings and values column is derived from data
        if 'dtype' not in kwargs:
            kwargs['dtype'] = {'Value': None, **{col: str for col in range(999)}}
        return pd.read_csv(memory_file, sep='~', **kwargs)

    @tidy_cellset
    @require_pandas
    def extract_cellset_dataframe_shaped(self, cellset_id: str, sandbox_name: str = None,
                                         display_attribute: bool = False, **kwargs) -> 'pd.DataFrame':
        """ Retrieves data from cellset in the shape of the query.
        Dimensions on rows can be stacked. One dimension must be placed on columns. Title selections are ignored.

        :param cellset_id
        :param sandbox_name: str
        :param display_attribute: bool, show element name or first attribute from MDX PROPERTIES clause
        """
        url = "/api/v1/Cellsets('{}')?$expand=" \
              "Axes($filter=Ordinal eq 0 or Ordinal eq 1;$expand=Tuples(" \
              "$expand=Members($select=Name{})),Hierarchies($select=Name))," \
              "Cells($select=Value)".format(cellset_id, ',Attributes' if display_attribute else '')

        url = add_url_parameters(url, **{"!sandbox": sandbox_name})
        response = self._rest.GET(url=url, **kwargs)
        response_json = response.json()

        column_headers = list()
        for column_tuple in response_json['Axes'][0]['Tuples']:
            member = column_tuple['Members'][0]
            if display_attribute and member['Attributes']:
                attribute_values = list(member['Attributes'].values())
                column_headers.append(attribute_values[0])
            else:
                column_headers.append(member['Name'])

        rows = response_json['Axes'][1]['Tuples']
        row_headers = [hierarchy['Name'] for hierarchy in response_json['Axes'][1]['Hierarchies']]
        cell_values = [cell['Value'] for cell in response_json['Cells']]

        headers = row_headers + column_headers
        body = []

        number_rows = len(rows)
        # avoid division by zero
        if not number_rows:
            return pd.DataFrame(body, columns=headers)

        number_cells = len(cell_values)
        number_columns = int(number_cells / number_rows)

        element_names_by_row = list()
        for row_tuple in rows:
            row = list()
            for member in row_tuple['Members']:
                if display_attribute and member['Attributes']:
                    attribute_values = list(member['Attributes'].values())
                    row.append(attribute_values[0])
                else:
                    row.append(member['Name'])

            element_names_by_row.append(tuple(row))

        if not number_columns:
            return pd.DataFrame(data=element_names_by_row, columns=headers)

        cell_values_by_row = [cell_values[cell_counter:cell_counter + number_columns]
                              for cell_counter
                              in range(0, number_cells, number_columns)]

        for element_tuple, cells in zip(element_names_by_row, cell_values_by_row):
            body.append(list(element_tuple) + cells)
        return pd.DataFrame(body, columns=headers, dtype=str)

    @require_pandas
    def extract_cellset_dataframe_pivot(self, cellset_id: str, dropna: bool = False, fill_value: bool = False,
                                        sandbox_name: str = None, use_compact_json: bool = False,
                                        **kwargs) -> 'pd.DataFrame':
        """ Extract a pivot table (pandas dataframe) from a cellset in TM1

        :param cellset_id:
        :param dropna:
        :param fill_value:
        :param kwargs:
        :param sandbox_name: str
        :param use_compact_json: bool
        :return:
        """

        data = self.extract_cellset(
            cellset_id=cellset_id,
            delete_cellset=False,
            sandbox_name=sandbox_name,
            use_compact_json=use_compact_json,
            **kwargs)

        cube, titles, rows, columns = self.extract_cellset_composition(
            cellset_id=cellset_id,
            delete_cellset=True,
            sandbox_name=sandbox_name,
            **kwargs)

        df = build_pandas_dataframe_from_cellset(data, multiindex=False)
        return pd.pivot_table(
            data=df,
            index=[dimension_name_from_element_unique_name(hierarchy_unique_name) for hierarchy_unique_name in rows],
            columns=[dimension_name_from_element_unique_name(hierarchy_unique_name) for hierarchy_unique_name in
                     columns],
            values=["Values"],
            dropna=dropna,
            fill_value=fill_value,
            aggfunc='sum')

    def extract_cellset(
            self,
            cellset_id: str,
            cell_properties: Iterable[str] = None,
            top: int = None,
            skip: int = None,
            delete_cellset: bool = True,
            skip_contexts: bool = False,
            skip_zeros: bool = False,
            skip_consolidated_cells: bool = False,
            skip_rule_derived_cells: bool = False,
            sandbox_name: str = None,
            element_unique_names: bool = True,
            skip_cell_properties: bool = False,
            use_compact_json: bool = False,
            **kwargs) -> CaseAndSpaceInsensitiveTuplesDict:
        """ Execute cellset and return the cells with their properties

        :param skip_contexts:
        :param delete_cellset:
        :param cellset_id:
        :param cell_properties: properties to be queried from the cell. E.g. Value, Ordinal, RuleDerived, ...
        :param top: Int, number of cells to return (counting from top)
        :param skip: Int, number of cells to skip (counting from top)
        :param skip_zeros: skip zeros in cellset (irrespective of zero suppression in MDX / view)
        :param skip_consolidated_cells: skip consolidated cells in cellset
        :param skip_rule_derived_cells: skip rule derived cells in cellset
        :param sandbox_name: str
        :param element_unique_names: '[d1].[h1].[e1]' or 'e1'
        :param skip_cell_properties: cell values in result dictionary, instead of cell_properties dictionary
        :param use_compact_json: bool
        :return: Content in sweet concise strcuture.
        """
        if not cell_properties:
            cell_properties = ['Value']

        raw_cellset = self.extract_cellset_raw(
            cellset_id,
            cell_properties=cell_properties,
            elem_properties=['UniqueName'],
            member_properties=['UniqueName'],
            top=top,
            skip=skip,
            skip_contexts=skip_contexts,
            delete_cellset=delete_cellset,
            skip_zeros=skip_zeros,
            skip_consolidated_cells=skip_consolidated_cells,
            skip_rule_derived_cells=skip_rule_derived_cells,
            sandbox_name=sandbox_name,
            include_hierarchies=False,
            use_compact_json=use_compact_json,
            **kwargs)

        return Utils.build_content_from_cellset_dict(
            raw_cellset_as_dict=raw_cellset,
            top=top,
            element_unique_names=element_unique_names,
            skip_cell_properties=skip_cell_properties)

    def create_cellset(self, mdx: str, sandbox_name: str = None, **kwargs) -> str:
        """ Execute MDX in order to create cellset at server. return the cellset-id

        :param mdx: MDX Query, as string
        :param sandbox_name: str
        :return:
        """
        url = '/api/v1/ExecuteMDX'
        url = add_url_parameters(url, **{"!sandbox": sandbox_name})
        data = {
            'MDX': mdx
        }
        response = self._rest.POST(url=url, data=json.dumps(data, ensure_ascii=False), **kwargs)
        cellset_id = response.json()['ID']
        return cellset_id

    def create_cellset_from_view(self, cube_name: str, view_name: str, private: bool, sandbox_name: str = None,
                                 **kwargs) -> str:
        """ create cellset from a cube view. return the cellset-id

        :param cube_name: String, name of the cube
        :param view_name: String, name of the view
        :param private: True (private) or False (public)
        :param kwargs:
        :param sandbox_name: str
        :return:
        """
        url = format_url("/api/v1/Cubes('{cube_name}')/{views}('{view_name}')/tm1.Execute",
                         cube_name=cube_name,
                         views='PrivateViews' if private else 'Views',
                         view_name=view_name)
        url = add_url_parameters(url, **{"!sandbox": sandbox_name})
        return self._rest.POST(url=url, **kwargs).json()['ID']

    def transaction_log_is_active(self, cube_name: str) -> bool:
        mdx = f"""
        SELECT {{[}}Cubes].[{cube_name}]}} ON 0, {{[}}CubeProperties].[LOGGING]}} ON 1 FROM [}}CubeProperties]
        """
        values = self.execute_mdx_values(mdx)
        return case_and_space_insensitive_equals(values[0], "YES")

    def deactivate_transactionlog(self, *args: str, **kwargs) -> Response:
        """ Deactivate Transactionlog for one or many cubes

        :param args: one or many cube names
        :return:
        """
        value = "NO"
        element_tuple = (args[0], "Logging")
        return self.write_value(value=value, cube_name="}CubeProperties", element_tuple=element_tuple, **kwargs)

    def activate_transactionlog(self, *args: str, **kwargs) -> Response:
        """ Activate Transactionlog for one or many cubes

        :param args: one or many cube names
        :return:
        """

        value = "YES"
        element_tuple = (args[0], "Logging")
        return self.write_value(value=value, cube_name="}CubeProperties", element_tuple=element_tuple, **kwargs)

    def begin_changeset(self) -> str:
        """ begin a change set

        :return: Change set ID
        """

        url = "/api/v1/BeginChangeSet"
        return self._rest.POST(url).json()['value']

    def end_changeset(self, change_set: str) -> Response:
        """end a change set

        :return: Change set ID
        """

        url = "/api/v1/EndChangeSet"
        data = {"ChangeSetID": change_set}
        return self._rest.POST(url, data=json.dumps(data, ensure_ascii=False))

    def undo_changeset(self, changeset: str) -> Response:
        """undo a changeset. Similar to rolling back transactions.

        :return: Change set ID
        """

        url = "/api/v1/UndoChangeSet"
        data = {"ChangeSetID": changeset}
        return self._rest.POST(url, data=json.dumps(data, ensure_ascii=False))

    def delete_cellset(self, cellset_id: str, sandbox_name: str = None, **kwargs) -> Response:
        """ Delete a cellset

        :param cellset_id:
        :param sandbox_name: str
        :return:
        """
        url = "/api/v1/Cellsets('{}')".format(cellset_id)
        url = add_url_parameters(url, **{"!sandbox": sandbox_name})
        return self._rest.DELETE(url, **kwargs)

    def get_cellset_cells_count(self, mdx: str) -> int:
        """ Execute MDX in order to understand how many cells are in a cellset

        :param mdx: MDX Query, as string
        :return: Number of Cells in the CellSet
        """
        warnings.simplefilter('always', PendingDeprecationWarning)
        warnings.warn(
            "Function deprecated. Use execute_mdx_cellcount(self, mdx) instead.",
            PendingDeprecationWarning
        )
        warnings.simplefilter('default', PendingDeprecationWarning)
        return self.execute_mdx_cellcount(mdx)

    def get_view_content(self, cube_name: str, view_name: str, cell_properties: Iterable[str] = None,
                         private: bool = False, top: int = None):
        warnings.simplefilter('always', PendingDeprecationWarning)
        warnings.warn(
            "Function deprecated. Use execute_view instead.",
            PendingDeprecationWarning
        )
        warnings.simplefilter('default', PendingDeprecationWarning)
        return self.execute_view(cube_name, view_name, private, cell_properties, top)

    @staticmethod
    def _extract_string_set_from_rows_and_values(
            rows_and_values: CaseAndSpaceInsensitiveTuplesDict,
            exclude_empty_cells: bool) -> CaseAndSpaceInsensitiveSet:
        """ Helper function for execute_..._string_set methods

        :param rows_and_values:
        :param exclude_empty_cells:
        :return:
        """
        result_set = CaseAndSpaceInsensitiveSet()
        for row_elements, cell_values in rows_and_values.items():
            for row_element in row_elements:
                result_set.add(row_element)
            for cell_value in cell_values:
                if isinstance(cell_value, str):
                    if cell_value or not exclude_empty_cells:
                        result_set.add(cell_value)
        return result_set

    def sandbox_exists(self, sandbox_name) -> bool:
        sandbox_service = SandboxService(self._rest)
        return sandbox_service.exists(sandbox_name)

    def _get_attributes_by_dimension(self, cube: str, **kwargs) -> Dict[str, List[str]]:
        from TM1py import ElementService
        element_service = ElementService(self._rest)

        attributes_by_dimension = CaseAndSpaceInsensitiveDict()
        for dimension_name in self.get_dimension_names_for_writing(cube):
            attributes_by_dimension[dimension_name] = element_service.get_element_attribute_names(
                dimension_name,
                dimension_name,
                **kwargs)

        return attributes_by_dimension
