# -*- coding: utf-8 -*-
import json
from typing import Dict, Tuple, List, Optional

from requests import Response

from TM1py.Objects import Hierarchy, Element, ElementAttribute
from TM1py.Services.ElementService import ElementService
from TM1py.Services.ObjectService import ObjectService
from TM1py.Services.RestService import RestService
from TM1py.Services.SubsetService import SubsetService
from TM1py.Utils.Utils import case_and_space_insensitive_equals, format_url, CaseAndSpaceInsensitiveDict, \
    CaseAndSpaceInsensitiveSet


class HierarchyService(ObjectService):
    """ Service to handle Object Updates for TM1 Hierarchies
    
    """

    # Tuple with TM1 Versions where Edges need to be created through TI, due to bug:
    # https://www.ibm.com/developerworks/community/forums/html/topic?id=75f2b99e-6961-4c71-9364-1d5e1e083eff
    EDGES_WORKAROUND_VERSIONS = ('11.0.002', '11.0.003', '11.1.000')

    def __init__(self, rest: RestService):
        super().__init__(rest)
        self.subsets = SubsetService(rest)
        self.elements = ElementService(rest)

    def create(self, hierarchy: Hierarchy, **kwargs):
        """ Create a hierarchy in an existing dimension

        :param hierarchy:
        :return:
        """
        url = format_url("/api/v1/Dimensions('{}')/Hierarchies", hierarchy.dimension_name)
        response = self._rest.POST(url, hierarchy.body, **kwargs)
        return response

    def get(self, dimension_name: str, hierarchy_name: str, **kwargs):
        """ get hierarchy

        :param dimension_name: name of the dimension
        :param hierarchy_name: name of the hierarchy
        :return:
        """
        url = format_url(
            "/api/v1/Dimensions('{}')/Hierarchies('{}')?$expand=Edges,Elements,ElementAttributes,Subsets,DefaultMember",
            dimension_name,
            hierarchy_name)
        response = self._rest.GET(url, **kwargs)
        return Hierarchy.from_dict(response.json())

    def get_all_names(self, dimension_name: str, **kwargs):
        """ get all names of existing Hierarchies in a dimension

        :param dimension_name:
        :return:
        """
        url = format_url("/api/v1/Dimensions('{}')/Hierarchies?$select=Name", dimension_name)
        response = self._rest.GET(url, **kwargs)
        return [hierarchy["Name"] for hierarchy in response.json()["value"]]

    def update(self, hierarchy: Hierarchy, **kwargs) -> List[Response]:
        """ update a hierarchy. It's a two step process: 
        1. Update Hierarchy
        2. Update Element-Attributes

        Function caters for Bug with Edge Creation:
        https://www.ibm.com/developerworks/community/forums/html/topic?id=75f2b99e-6961-4c71-9364-1d5e1e083eff

        :param hierarchy: instance of TM1py.Hierarchy
        :return: list of responses
        """
        # functions returns multiple responses
        responses = list()
        # 1. Update Hierarchy
        url = format_url("/api/v1/Dimensions('{}')/Hierarchies('{}')", hierarchy.dimension_name, hierarchy.name)
        # Workaround EDGES: Handle Issue, that Edges cant be created in one batch with the Hierarchy in certain versions
        hierarchy_body = hierarchy.body_as_dict
        if self.version[0:8] in self.EDGES_WORKAROUND_VERSIONS:
            del hierarchy_body["Edges"]
        responses.append(self._rest.PATCH(url, json.dumps(hierarchy_body), **kwargs))

        # 2. Update Attributes
        responses.append(self.update_element_attributes(hierarchy=hierarchy, **kwargs))

        # Workaround EDGES
        if self.version[0:8] in self.EDGES_WORKAROUND_VERSIONS:
            from TM1py.Services import ProcessService
            process_service = ProcessService(self._rest)
            ti_function = "HierarchyElementComponentAdd('{}', '{}', '{}', '{}', {});"
            ti_statements = [ti_function.format(hierarchy.dimension_name, hierarchy.name,
                                                edge[0],
                                                edge[1],
                                                hierarchy.edges[(edge[0], edge[1])])
                             for edge
                             in hierarchy.edges]
            responses.append(process_service.execute_ti_code(lines_prolog=ti_statements, **kwargs))

        return responses

    def update_or_create(self, hierarchy: Hierarchy, **kwargs):
        """ update if exists else create

        :param Hierarchy:
        :return:
        """
        if self.exists(dimension_name=hierarchy.dimension_name, hierarchy_name=hierarchy.name, **kwargs):
            self.update(hierarchy=hierarchy, **kwargs)
        else:
            self.create(hierarchy=hierarchy, **kwargs)

    def exists(self, dimension_name: str, hierarchy_name: str, **kwargs) -> bool:
        """

        :param dimension_name: 
        :param hierarchy_name: 
        :return: 
        """
        url = format_url("/api/v1/Dimensions('{}')/Hierarchies('{}')", dimension_name, hierarchy_name)
        return self._exists(url, **kwargs)

    def delete(self, dimension_name: str, hierarchy_name: str, **kwargs) -> Response:
        url = format_url("/api/v1/Dimensions('{}')/Hierarchies('{}')", dimension_name, hierarchy_name)
        return self._rest.DELETE(url, **kwargs)

    def get_hierarchy_summary(self, dimension_name: str, hierarchy_name: str, **kwargs) -> Dict[str, int]:
        hierarchy_properties = ("Elements", "Edges", "ElementAttributes", "Members", "Levels")
        url = format_url(
            "/api/v1/Dimensions('{}')/Hierarchies('{}')?$expand=Edges/$count,Elements/$count,"
            "ElementAttributes/$count,Members/$count,Levels/$count&$select=Cardinality",
            dimension_name,
            hierarchy_name)
        hierary_summary_raw = self._rest.GET(url, **kwargs).json()

        return {hierarchy_property: hierary_summary_raw[hierarchy_property + "@odata.count"]
                for hierarchy_property
                in hierarchy_properties}

    def update_element_attributes(self, hierarchy: Hierarchy, **kwargs):
        """ Update the elementattributes of a hierarchy

        :param hierarchy: Instance of TM1py.Hierarchy
        :return:
        """
        # get existing attributes first
        existing_element_attributes = self.elements.get_element_attributes(
            dimension_name=hierarchy.dimension_name,
            hierarchy_name=hierarchy.name,
            **kwargs)
        existing_element_attributes = CaseAndSpaceInsensitiveDict({ea.name: ea for ea in existing_element_attributes})

        attributes_to_create = list()
        attributes_to_delete = list()
        attributes_to_update = list()

        for element_attribute in hierarchy.element_attributes:
            if element_attribute.name not in existing_element_attributes:
                attributes_to_create.append(element_attribute)
                continue

            existing_element_attribute = existing_element_attributes[element_attribute.name]
            if not existing_element_attribute.attribute_type == element_attribute.attribute_type:
                attributes_to_update.append(element_attribute)
                continue

        for existing_element_attribute in existing_element_attributes:
            if existing_element_attribute not in CaseAndSpaceInsensitiveSet(
                    [ea.name for ea in hierarchy.element_attributes]):
                attributes_to_delete.append(existing_element_attribute)

        for element_attribute in attributes_to_create:
            self.elements.create_element_attribute(
                dimension_name=hierarchy.dimension_name,
                hierarchy_name=hierarchy.name,
                element_attribute=element_attribute,
                **kwargs)

        for element_attribute in attributes_to_delete:
            self.elements.delete_element_attribute(
                dimension_name=hierarchy.dimension_name,
                hierarchy_name=hierarchy.name,
                element_attribute=element_attribute,
                **kwargs)

        for element_attribute in attributes_to_update:
            self.elements.delete_element_attribute(
                dimension_name=hierarchy.dimension_name,
                hierarchy_name=hierarchy.name,
                element_attribute=element_attribute.name,
                **kwargs)
            self.elements.create_element_attribute(
                dimension_name=hierarchy.dimension_name,
                hierarchy_name=hierarchy.name,
                element_attribute=element_attribute,
                **kwargs)

    def get_default_member(self, dimension_name: str, hierarchy_name: str = None, **kwargs) -> Optional[str]:
        """ Get the defined default_member for a Hierarchy.
        Will return the element with index 1, if default member is not specified explicitly in }HierarchyProperty Cube

        :param dimension_name:
        :param hierarchy_name:
        :return: String, name of Member
        """
        url = format_url(
            "/api/v1/Dimensions('{dimension}')/Hierarchies('{hierarchy}')/DefaultMember",
            dimension=dimension_name,
            hierarchy=hierarchy_name if hierarchy_name else dimension_name)
        response = self._rest.GET(url=url, **kwargs)

        if not response.text:
            return None
        return response.json()["Name"]

    def update_default_member(self, dimension_name: str, hierarchy_name: str = None, member_name: str = "",
                              **kwargs) -> Response:
        """ Update the default member of a hierarchy.
        Currently implemented through TI, since TM1 API does not supports default member updates yet.

        :param dimension_name:
        :param hierarchy_name:
        :param member_name:
        :return:
        """
        from TM1py import ProcessService, CellService
        if hierarchy_name and not case_and_space_insensitive_equals(dimension_name, hierarchy_name):
            dimension = "{}:{}".format(dimension_name, hierarchy_name)
        else:
            dimension = dimension_name
        cells = {(dimension, 'hierarchy0', 'defaultMember'): member_name}

        CellService(self._rest).write_values(
            cube_name="}HierarchyProperties",
            cellset_as_dict=cells,
            dimensions=('}Dimensions', '}Hierarchies', '}HierarchyProperties'),
            **kwargs)

        return ProcessService(self._rest).execute_ti_code(
            lines_prolog=format_url("RefreshMdxHierarchy('{}');", dimension_name),
            **kwargs)

    def remove_all_edges(self, dimension_name: str, hierarchy_name: str = None, **kwargs) -> Response:
        if not hierarchy_name:
            hierarchy_name = dimension_name
        url = format_url("/api/v1/Dimensions('{}')/Hierarchies('{}')", dimension_name, hierarchy_name)
        body = {
            "Edges": []
        }
        return self._rest.PATCH(url=url, data=json.dumps(body), **kwargs)

    def remove_edges_under_consolidation(self, dimension_name: str, hierarchy_name: str,
                                         consolidation_element: str, **kwargs) -> List[Response]:
        """
        :param dimension_name: Name of the dimension
        :param hierarchy_name: Name of the hierarchy
        :param consolidation_element: Name of the Consolidated element
        :return: response
        """
        hierarchy = self.get(dimension_name, hierarchy_name)
        from TM1py.Services import ElementService
        element_service = ElementService(self._rest)
        elements_under_consolidations = element_service.get_members_under_consolidation(dimension_name, hierarchy_name,
                                                                                        consolidation_element)
        elements_under_consolidations.append(consolidation_element)
        remove_edges = []
        for (parent, component) in hierarchy.edges:
            if parent in elements_under_consolidations and component in elements_under_consolidations:
                remove_edges.append((parent, component))
        hierarchy.remove_edges(remove_edges)
        return self.update(hierarchy, **kwargs)

    def add_edges(self, dimension_name: str, hierarchy_name: str = None, edges: Dict[Tuple[str, str], int] = None,
                  **kwargs) -> Response:
        """ Add Edges to hierarchy. Fails if one edge already exists.

        :param dimension_name:
        :param hierarchy_name:
        :param edges:
        :return:
        """
        return self.elements.add_edges(dimension_name, hierarchy_name, edges, **kwargs)

    def add_elements(self, dimension_name: str, hierarchy_name: str, elements: List[Element], **kwargs):
        """ Add elements to hierarchy. Fails if one element already exists.

        :param dimension_name:
        :param hierarchy_name:
        :param elements:
        :return:
        """
        return self.elements.add_elements(dimension_name, hierarchy_name, elements, **kwargs)

    def add_element_attributes(self, dimension_name: str, hierarchy_name: str,
                               element_attributes: List[ElementAttribute], **kwargs):
        """ Add element attributes to hierarchy. Fails if one element attribute already exists.

        :param dimension_name:
        :param hierarchy_name:
        :param element_attributes:
        :return:
        """
        return self.elements.add_element_attributes(dimension_name, hierarchy_name, element_attributes, **kwargs)

    def is_balanced(self, dimension_name: str, hierarchy_name: str, **kwargs):
        """ Check if hierarchy is balanced

        :param dimension_name:
        :param hierarchy_name:
        :return:
        """
        url = format_url(
            "/api/v1/Dimensions('{}')/Hierarchies('{}')/Structure/$value",
            dimension_name,
            hierarchy_name)
        structure = int(self._rest.GET(url, **kwargs).text)
        # 0 = balanced, 2 = unbalanced
        if structure == 0:
            return True
        elif structure == 2:
            return False
        else:
            raise RuntimeError(f"Unexpected return value from TM1 API request: {str(structure)}")
