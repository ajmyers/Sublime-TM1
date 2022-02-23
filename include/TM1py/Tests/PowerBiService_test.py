import configparser
import unittest
from pathlib import Path

from TM1py import MDXView
from TM1py.Objects import Cube, Dimension, Element, Hierarchy, ElementAttribute
from TM1py.Services import TM1Service
from .Utils import skip_if_no_pandas


class TestPowerBiService(unittest.TestCase):
    tm1: TM1Service
    prefix = 'TM1py_Tests_PowerBiService_'
    cube_name = prefix + "Cube"
    view_name = prefix + "View"
    dimension_name = prefix + "Dimension"
    dimension_names = [
        prefix + 'Dimension1',
        prefix + 'Dimension2',
        prefix + 'Dimension3']
    string_cube_name = prefix + "StringCube"
    string_dimension_names = [
        prefix + 'StringDimension1',
        prefix + 'StringDimension2',
        prefix + 'StringDimension3']
    cells_in_string_cube = {
        ('d1e1', 'd2e1', 'd3e1'): 'String1',
        ('d1e2', 'd2e2', 'd3e2'): 'String2',
        ('d1e3', 'd2e3', 'd3e3'): 'String3'}

    cube_name_rps1 = prefix + "Cube" + "_RPS1"
    cube_name_rps2 = prefix + "Cube" + "_RPS2"
    dimension_name_rps1 = prefix + "Dimension" + "_RPS1"
    dimension_name_rps2 = prefix + "Dimension" + "_RPS2"

    MDX_TEMPLATE = """
    SELECT 
    {rows} ON ROWS,
    {columns} ON COLUMNS
    FROM {cube}
    WHERE {where}
    """

    MDX_TEMPLATE_NON_EMPTY = """
    SELECT 
    NON EMPTY {rows} ON ROWS,
    NON EMPTY {columns} ON COLUMNS
    FROM {cube}
    WHERE {where}
    """

    MDX_TEMPLATE_SHORT = """
    SELECT 
    {rows} ON ROWS,
    {columns} ON COLUMNS
    FROM {cube}
    """

    @classmethod
    def setUpClass(cls):
        """
        Establishes a connection to TM1 and creates TM! objects to use across all tests
        """

        # Connection to TM1
        cls.config = configparser.ConfigParser()
        cls.config.read(Path(__file__).parent.joinpath('config.ini'))
        cls.tm1 = TM1Service(**cls.config['tm1srv01'])

        # generate random coordinates
        cls.target_coordinates = list(zip(('Element ' + str(e) for e in range(1, 100)),
                                          ('Element ' + str(e) for e in range(1, 100)),
                                          ('Element ' + str(e) for e in range(1, 100))))

        # Build Dimensions
        for dimension_name in cls.dimension_names:
            elements = [Element('Element {}'.format(str(j)), 'Numeric') for j in range(1, 1001)]
            element_attributes = [ElementAttribute("Attr1", "String"),
                                  ElementAttribute("Attr2", "Numeric"),
                                  ElementAttribute("Attr3", "Numeric")]
            hierarchy = Hierarchy(dimension_name=dimension_name,
                                  name=dimension_name,
                                  elements=elements,
                                  element_attributes=element_attributes)
            dimension = Dimension(dimension_name, [hierarchy])
            cls.tm1.dimensions.update_or_create(dimension)
            attribute_cube = "}ElementAttributes_" + dimension_name
            attribute_values = dict()
            for element in elements:
                attribute_values[(element.name, "Attr1")] = "TM1py"
                attribute_values[(element.name, "Attr2")] = "2"
                attribute_values[(element.name, "Attr3")] = "3"
            cls.tm1.cubes.cells.write_values(attribute_cube, attribute_values)

        # Build Cube
        cube = Cube(cls.cube_name, cls.dimension_names)
        if not cls.tm1.cubes.exists(cls.cube_name):
            cls.tm1.cubes.create(cube)

        # Sum of all the values that we write in the cube. serves as a checksum.
        cls.total_value = 0

        # cellset of data that shall be written
        cls.cellset = {}
        for element1, element2, element3 in cls.target_coordinates:
            value = 1
            cls.cellset[(element1, element2, element3)] = value
            # update the checksum
            cls.total_value += value

        # Fill cube with values
        cls.tm1.cubes.cells.write_values(cls.cube_name, cls.cellset)

        # Elements
        cls.years = ("No Year", "1989", "1990", "1991", "1992")
        cls.extra_year = "4321"
        # Element Attributes
        cls.attributes = ('Previous Year', 'Next Year')
        cls.alias_attributes = ("Financial Year",)

        # create dimension with a default hierarchy
        d = Dimension(cls.dimension_name)
        h = Hierarchy(cls.dimension_name, cls.dimension_name)
        h.add_element('Total Years', 'Consolidated')
        h.add_element('All Consolidations', 'Consolidated')
        h.add_edge("All Consolidations", "Total Years", 1)
        for year in cls.years:
            h.add_element(year, 'Numeric')
            h.add_edge('Total Years', year, 1)
        for attribute in cls.attributes:
            h.add_element_attribute(attribute, "String")
        for attribute in cls.alias_attributes:
            h.add_element_attribute(attribute, "Alias")
        d.add_hierarchy(h)
        cls.tm1.dimensions.update_or_create(d)

        # write attribute values
        cls.tm1.cubes.cells.write_value('1988', '}ElementAttributes_' + cls.dimension_name, ('1989', 'Previous Year'))
        cls.tm1.cubes.cells.write_value('1989', '}ElementAttributes_' + cls.dimension_name, ('1990', 'Previous Year'))
        cls.tm1.cubes.cells.write_value('1990', '}ElementAttributes_' + cls.dimension_name, ('1991', 'Previous Year'))
        cls.tm1.cubes.cells.write_value('1991', '}ElementAttributes_' + cls.dimension_name, ('1992', 'Previous Year'))

        cls.tm1.cubes.cells.write_value('1988/89', '}ElementAttributes_' + cls.dimension_name,
                                        ('1989', 'Financial Year'))
        cls.tm1.cubes.cells.write_value('1989/90', '}ElementAttributes_' + cls.dimension_name,
                                        ('1990', 'Financial Year'))
        cls.tm1.cubes.cells.write_value('1990/91', '}ElementAttributes_' + cls.dimension_name,
                                        ('1991', 'Financial Year'))
        cls.tm1.cubes.cells.write_value('1991/92', '}ElementAttributes_' + cls.dimension_name,
                                        ('1992', 'Financial Year'))

    #    @skip_if_no_pandas
    def add_unbalanced_hierarchy(self, hierarchy_name):
        dimension = self.tm1.dimensions.get(self.dimension_name)
        # other hierarchy
        hierarchy = Hierarchy(name=hierarchy_name, dimension_name=self.dimension_name)

        hierarchy.add_element("Total Years Unbalanced", "Consolidated")
        hierarchy.add_element('1989', 'Numeric')
        hierarchy.add_element('1990', 'Numeric')
        hierarchy.add_element('1991', 'Numeric')
        hierarchy.add_edge("Total Years Unbalanced", "1989", 1)
        hierarchy.add_edge("Total Years Unbalanced", "1990", 1)
        dimension.add_hierarchy(hierarchy)

        self.tm1.dimensions.update(dimension)

    @skip_if_no_pandas
    def test_execute_mdx(self):
        mdx = self.MDX_TEMPLATE.format(
            rows="{[" + self.dimension_names[0] + "].[Element1], [" + self.dimension_names[0] + "].[Element2]}",
            columns="{[" + self.dimension_names[1] + "].[Element1], [" + self.dimension_names[1] + "].[Element2]}",
            cube=self.cube_name,
            where="[" + self.dimension_names[2] + "].[Element1]")
        df = self.tm1.power_bi.execute_mdx(mdx)

        self.assertEqual(len(df), 2)

        self.assertEqual(
            tuple(df.columns),
            (self.dimension_names[0], "Element 1", "Element 2"))

        element1 = df.loc[df[self.dimension_names[0]] == "Element 1"]
        self.assertEqual(
            tuple(element1.values[0]),
            ("Element 1", "1.0", None))

    @skip_if_no_pandas
    def test_execute_view(self):
        mdx = self.MDX_TEMPLATE.format(
            rows="{[" + self.dimension_names[0] + "].[Element1], [" + self.dimension_names[0] + "].[Element2]}",
            columns="{[" + self.dimension_names[1] + "].[Element1], [" + self.dimension_names[1] + "].[Element2]}",
            cube=self.cube_name,
            where="[" + self.dimension_names[2] + "].[Element1]")

        self.tm1.cubes.views.create(MDXView(self.cube_name, self.view_name, mdx), private=False)

        df = self.tm1.power_bi.execute_view(self.cube_name, self.view_name, private=False)

        self.assertEqual(len(df), 2)

        self.assertEqual(
            tuple(df.columns),
            (self.dimension_names[0], "Element 1", "Element 2"))

        element1 = df.loc[df[self.dimension_names[0]] == "Element 1"]
        self.assertEqual(
            tuple(element1.values[0]),
            ("Element 1", "1.0", None))

    @skip_if_no_pandas
    def test_get_member_properties_default(self):
        members = self.tm1.power_bi.get_member_properties(
            dimension_name=self.dimension_name,
            hierarchy_name=self.dimension_name,
            member_selection=None,
            skip_consolidations=True,
            attributes=None)

        self.assertEqual(len(members), 5)

        self.assertEqual(
            tuple(members.columns),
            (self.dimension_name, "Type", "Previous Year", "Next Year", "Financial Year", "level001", "level000"))

        # 1989
        year_1989 = members.loc[members[self.dimension_name] == "1989"]
        self.assertEqual(
            tuple(year_1989.values[0]),
            ("1989", "Numeric", "1988", "", "1988/89", "Total Years", "All Consolidations"))

        # 1992
        year_1992 = members.loc[members[self.dimension_name] == "1992"]
        self.assertEqual(
            tuple(year_1992.values[0]),
            ("1992", "Numeric", "1991", "", "1991/92", "Total Years", "All Consolidations"))

    @skip_if_no_pandas
    def test_get_member_properties_attributes(self):
        members = self.tm1.power_bi.get_member_properties(
            dimension_name=self.dimension_name,
            hierarchy_name=self.dimension_name,
            member_selection=None,
            skip_consolidations=True,
            attributes=["Previous Year"])

        self.assertEqual(len(members), 5)

        self.assertEqual(
            tuple(members.columns),
            (self.dimension_name, "Type", "Previous Year", "level001", "level000"))

        # 1989
        year_1989 = members.loc[members[self.dimension_name] == "1989"]
        self.assertEqual(
            tuple(year_1989.values[0]),
            ("1989", "Numeric", "1988", "Total Years", "All Consolidations"))

        # 1992
        year_1992 = members.loc[members[self.dimension_name] == "1992"]
        self.assertEqual(
            tuple(year_1992.values[0]),
            ("1992", "Numeric", "1991", "Total Years", "All Consolidations"))

    @skip_if_no_pandas
    def test_get_member_properties_no_attributes(self):
        members = self.tm1.power_bi.get_member_properties(
            dimension_name=self.dimension_name,
            hierarchy_name=self.dimension_name,
            member_selection=None,
            skip_consolidations=True,
            attributes=[])

        self.assertEqual(
            tuple(members.columns),
            (self.dimension_name, "Type", "level001", "level000"))

        self.assertEqual(len(members), 5)

        # 1989
        year_1989 = members.loc[members[self.dimension_name] == "1989"]
        self.assertEqual(
            tuple(year_1989.values[0]),
            ("1989", "Numeric", "Total Years", "All Consolidations"))

        # 1992
        year_1992 = members.loc[members[self.dimension_name] == "1992"]
        self.assertEqual(
            tuple(year_1992.values[0]),
            ("1992", "Numeric", "Total Years", "All Consolidations"))

    @skip_if_no_pandas
    def test_get_member_properties_member_selection(self):
        members = self.tm1.power_bi.get_member_properties(
            dimension_name=self.dimension_name,
            hierarchy_name=self.dimension_name,
            member_selection=f"{{ [{self.dimension_name}].[1989], [{self.dimension_name}].[1992] }}",
            skip_consolidations=True,
            attributes=None)

        self.assertEqual(
            tuple(members.columns),
            (self.dimension_name, "Type", "Previous Year", "Next Year", "Financial Year", "level001", "level000"))

        self.assertEqual(len(members), 2)

        # 1989
        year_1989 = members.loc[members[self.dimension_name] == "1989"]
        self.assertEqual(
            tuple(year_1989.values[0]),
            ("1989", "Numeric", "1988", "", "1988/89", "Total Years", "All Consolidations"))

        # 1992
        year_1992 = members.loc[members[self.dimension_name] == "1992"]
        self.assertEqual(
            tuple(year_1992.values[0]),
            ("1992", "Numeric", "1991", "", "1991/92", "Total Years", "All Consolidations"))

    @skip_if_no_pandas
    def test_get_member_properties_skip_parents(self):
        members = self.tm1.power_bi.get_member_properties(
            dimension_name=self.dimension_name,
            hierarchy_name=self.dimension_name,
            member_selection=f"{{ [{self.dimension_name}].[1989], [{self.dimension_name}].[1992] }}",
            skip_consolidations=True,
            attributes=None,
            skip_parents=True)

        self.assertEqual(
            tuple(members.columns),
            (self.dimension_name, "Type", "Previous Year", "Next Year", "Financial Year"))

        self.assertEqual(len(members), 2)

        # 1989
        year_1989 = members.loc[members[self.dimension_name] == "1989"]
        self.assertEqual(
            tuple(year_1989.values[0]),
            ("1989", "Numeric", "1988", "", "1988/89"))

        # 1992
        year_1992 = members.loc[members[self.dimension_name] == "1992"]
        self.assertEqual(
            tuple(year_1992.values[0]),
            ("1992", "Numeric", "1991", "", "1991/92"))

    # alternate hierarchies cause issues. must be addressed.
    @unittest.skip
    def test_get_member_properties_unbalanced(self):
        hierarchy_name = "Unbalanced Hierarchy"
        self.add_unbalanced_hierarchy(hierarchy_name=hierarchy_name)

        members = self.tm1.power_bi.get_member_properties(
            dimension_name=self.dimension_name,
            hierarchy_name=hierarchy_name,
            member_selection=None,
            skip_consolidations=False,
            attributes=None)

        self.assertEqual(
            tuple(members.columns),
            (self.dimension_name, "Type", "Previous Year", "Next Year", "Financial Year", "level001", "level000"))

    @skip_if_no_pandas
    def test_get_member_properties_include_consolidations(self):
        members = self.tm1.power_bi.get_member_properties(
            dimension_name=self.dimension_name,
            hierarchy_name=self.dimension_name,
            member_selection=None,
            skip_consolidations=False,
            attributes=None)

        self.assertEqual(
            tuple(members.columns),
            (self.dimension_name, "Type", "Previous Year", "Next Year", "Financial Year", "level001", "level000"))
        self.assertEqual(
            tuple(members[self.dimension_name]),
            ("All Consolidations", "Total Years", "No Year", "1989", "1990", "1991", "1992"))

        row = members.loc[members[self.dimension_name] == "All Consolidations"]
        self.assertEqual(
            tuple(row.values[0]),
            ("All Consolidations", "Consolidated", "", "", "", "", ""))
        row = members.loc[members[self.dimension_name] == "Total Years"]
        self.assertEqual(
            tuple(row.values[0]),
            ("Total Years", "Consolidated", "", "", "", "", "All Consolidations"))
        row = members.loc[members[self.dimension_name] == "No Year"]
        self.assertEqual(
            tuple(row.values[0]),
            ("No Year", "Numeric", "", "", "", "Total Years", "All Consolidations"))
        row = members.loc[members[self.dimension_name] == "1989"]
        self.assertEqual(
            tuple(row.values[0]),
            ("1989", "Numeric", "1988", "", "1988/89", "Total Years", "All Consolidations"))
        row = members.loc[members[self.dimension_name] == "1992"]
        self.assertEqual(
            tuple(row.values[0]),
            ("1992", "Numeric", "1991", "", "1991/92", "Total Years", "All Consolidations"))

    @skip_if_no_pandas
    def test_get_member_properties_member_selection_and_attributes(self):
        members = self.tm1.power_bi.get_member_properties(
            dimension_name=self.dimension_name,
            hierarchy_name=self.dimension_name,
            member_selection=f"{{ [{self.dimension_name}].[1989], [{self.dimension_name}].[1990] }}",
            skip_consolidations=True,
            attributes=["Previous Year", "Financial Year"])

        self.assertEqual(
            tuple(members.columns),
            (self.dimension_name, "Type", "Previous Year", "Financial Year", "level001", "level000"))

        self.assertEqual(
            tuple(members[self.dimension_name]),
            ("1989", "1990"))

        row = members.loc[members[self.dimension_name] == "1989"]
        self.assertEqual(
            tuple(row.values[0]),
            ("1989", "Numeric", "1988", "1988/89", "Total Years", "All Consolidations"))

        row = members.loc[members[self.dimension_name] == "1990"]
        self.assertEqual(
            tuple(row.values[0]),
            ("1990", "Numeric", "1989", "1989/90", "Total Years", "All Consolidations"))

    @skip_if_no_pandas
    def test_get_member_properties_member_iterable_selection_and_attributes(self):
        members = self.tm1.power_bi.get_member_properties(
            dimension_name=self.dimension_name,
            hierarchy_name=self.dimension_name,
            member_selection=["1989", "1990"],
            skip_consolidations=True,
            attributes=["Previous Year", "Financial Year"])

        self.assertEqual(
            tuple(members.columns),
            (self.dimension_name, "Type", "Previous Year", "Financial Year", "level001", "level000"))

        self.assertEqual(
            tuple(members[self.dimension_name]),
            ("1989", "1990"))

        row = members.loc[members[self.dimension_name] == "1989"]
        self.assertEqual(
            tuple(row.values[0]),
            ("1989", "Numeric", "1988", "1988/89", "Total Years", "All Consolidations"))

        row = members.loc[members[self.dimension_name] == "1990"]
        self.assertEqual(
            tuple(row.values[0]),
            ("1990", "Numeric", "1989", "1989/90", "Total Years", "All Consolidations"))

    @skip_if_no_pandas
    def test_get_member_properties_member_iterable_selection_and_custom_parent_names(self):
        members = self.tm1.power_bi.get_member_properties(
            dimension_name=self.dimension_name,
            hierarchy_name=self.dimension_name,
            member_selection=["1989", "1990"],
            skip_consolidations=True,
            attributes=["Previous Year", "Financial Year"],
            level_names=["leaves", "parent1", "parent2"])

        self.assertEqual(
            tuple(members.columns),
            (self.dimension_name, "Type", "Previous Year", "Financial Year", "parent1", "parent2"))

        self.assertEqual(
            tuple(members[self.dimension_name]),
            ("1989", "1990"))

        row = members.loc[members[self.dimension_name] == "1989"]
        self.assertEqual(
            tuple(row.values[0]),
            ("1989", "Numeric", "1988", "1988/89", "Total Years", "All Consolidations"))

        row = members.loc[members[self.dimension_name] == "1990"]
        self.assertEqual(
            tuple(row.values[0]),
            ("1990", "Numeric", "1989", "1989/90", "Total Years", "All Consolidations"))

    @skip_if_no_pandas
    def test_get_member_properties_iterable_and_skip_consolidations(self):
        members = self.tm1.power_bi.get_member_properties(
            dimension_name=self.dimension_name,
            hierarchy_name=self.dimension_name,
            member_selection=["Total Years", "1989"],
            skip_consolidations=True,
            attributes=["Previous Year", "Financial Year"],
            level_names=["leaves", "parent1", "parent2"])

        self.assertEqual(
            tuple(members.columns),
            (self.dimension_name, "Type", "Previous Year", "Financial Year", "parent1", "parent2"))

        self.assertEqual(
            tuple(members[self.dimension_name]),
            ("1989",))

        row = members.loc[members[self.dimension_name] == "1989"]
        self.assertEqual(
            tuple(row.values[0]),
            ("1989", "Numeric", "1988", "1988/89", "Total Years", "All Consolidations"))

    @skip_if_no_pandas
    def test_get_member_properties_member_skip_parents_skip_attributes(self):
        members = self.tm1.power_bi.get_member_properties(
            dimension_name=self.dimension_name,
            hierarchy_name=self.dimension_name,
            member_selection=f"{{ [{self.dimension_name}].[1989], [{self.dimension_name}].[1990] }}",
            skip_parents=True,
            skip_consolidations=True,
            attributes=[])

        self.assertEqual(
            tuple(members.columns),
            (self.dimension_name, "Type"))

        self.assertEqual(
            tuple(members[self.dimension_name]),
            ("1989", "1990"))

        row = members.loc[members[self.dimension_name] == "1989"]
        self.assertEqual(
            tuple(row.values[0]),
            ("1989", "Numeric"))

        row = members.loc[members[self.dimension_name] == "1990"]
        self.assertEqual(
            tuple(row.values[0]),
            ("1990", "Numeric"))

    # Delete Cube and Dimensions
    @classmethod
    def teardown_class(cls):
        cls.tm1.cubes.delete(cls.cube_name)
        for dimension_name in cls.dimension_names:
            cls.tm1.dimensions.delete(dimension_name)
        cls.tm1.dimensions.delete(cls.dimension_name)
        cls.tm1.logout()


if __name__ == '__main__':
    unittest.main()
