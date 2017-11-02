import random
import unittest
import uuid

from TM1py.Objects import Dimension, Hierarchy, Subset, ElementAttribute, Element
from TM1py.Services import TM1Service

from .config import test_config


class TestSubsetMethods(unittest.TestCase):

    # Check if Dimensions exists. If not create it
    @classmethod
    def setup_class(cls):
        cls.tm1 = TM1Service(**test_config)

        # Do random stuff
        cls.random_string = str(uuid.uuid4())
        cls.private = bool(random.getrandbits(1))

        # Define Names
        cls.dimension_name = 'TM1py_unittest_dimension_' + cls.random_string
        cls.subset_name_static = 'TM1py_unittest_static_subset_' + cls.random_string
        cls.subset_name_dynamic = 'TM1py_unittest_dynamic_subset_' + cls.random_string

        # Instantiate Subsets
        cls.static_subset = Subset(dimension_name=cls.dimension_name,
                                   subset_name=cls.subset_name_static,
                                   elements=['USD', 'EUR', 'NZD'])
        cls.dynamic_subset = Subset(dimension_name=cls.dimension_name,
                                    subset_name=cls.subset_name_dynamic,
                                    expression='{ HIERARCHIZE( {TM1SUBSETALL( [' + cls.dimension_name + '] )} ) }')

        elements = [Element('USD', 'Numeric'),
                    Element('EUR', 'Numeric'),
                    Element('JPY', 'Numeric'),
                    Element('CNY', 'Numeric'),
                    Element('GBP', 'Numeric'),
                    Element('NZD', 'Numeric')]
        element_attributes = [ElementAttribute('Currency Name', 'String')]
        h = Hierarchy(cls.dimension_name, cls.dimension_name, elements, element_attributes)
        d = Dimension(cls.dimension_name, hierarchies=[h])
        cls.tm1.dimensions.create(d)

    # 1. Create subset
    def test_1create_subset(self):
        self.tm1.dimensions.subsets.create(self.static_subset, private=self.private)
        self.tm1.dimensions.hierarchies.subsets.create(self.dynamic_subset, private=self.private)

    # 2. Get subset
    def test_2get_subset(self):
        s = self.tm1.dimensions.hierarchies.subsets.get(dimension_name=self.dimension_name,
                                                        subset_name=self.subset_name_static,
                                                        private=self.private)
        self.assertEqual(self.static_subset.body, s.body)
        s = self.tm1.dimensions.hierarchies.subsets.get(dimension_name=self.dimension_name,
                                                        subset_name=self.subset_name_dynamic,
                                                        private=self.private)
        self.assertEqual(self.dynamic_subset.body, s.body)

    # 3. Update subset
    def test_3update_subset(self):
        s = self.tm1.dimensions.hierarchies.subsets.get(dimension_name=self.dimension_name,
                                                        subset_name=self.subset_name_static,
                                                        private=self.private)
        s.add_elements(['NZD'])
        # Update it
        self.tm1.dimensions.hierarchies.subsets.update(s, private=self.private)
        # Get it again
        s = self.tm1.dimensions.hierarchies.subsets.get(dimension_name=self.dimension_name,
                                                        subset_name=self.subset_name_static,
                                                        private=self.private)
        # Test it !
        self.assertEquals(len(s.elements), 4)
        # Get subset
        s = self.tm1.dimensions.hierarchies.subsets.get(dimension_name=self.dimension_name,
                                                        subset_name=self.subset_name_dynamic,
                                                        private=self.private)

        s.expression = '{{ [{}].[EUR], [{}].[USD] }})'.format(self.dimension_name, self.dimension_name)
        # Update it
        self.tm1.dimensions.hierarchies.subsets.update(subset=s, private=self.private)
        # Get it again
        s = self.tm1.dimensions.hierarchies.subsets.get(dimension_name=self.dimension_name,
                                                        subset_name=self.subset_name_dynamic,
                                                        private=self.private)
        # Test it !
        self.assertEquals(s.expression,
                          '{{ [{}].[EUR], [{}].[USD] }})'.format(self.dimension_name, self.dimension_name))

    # 4. Delete subsets
    def test_4delete_subset(self):
        self.tm1.dimensions.hierarchies.subsets.delete(dimension_name=self.dimension_name,
                                                       subset_name=self.subset_name_static,
                                                       private=self.private)
        self.tm1.dimensions.hierarchies.subsets.delete(dimension_name=self.dimension_name,
                                                       subset_name=self.subset_name_dynamic,
                                                       private=self.private)

    @classmethod
    def teardown_class(cls):
        cls.tm1.dimensions.delete(cls.dimension_name)
        cls.tm1.logout()

if __name__ == '__main__':
    unittest.main()
