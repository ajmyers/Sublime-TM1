# -*- coding: utf-8 -*-

import json


from TM1py.Exceptions import TM1pyException
from TM1py.Objects.Dimension import Dimension
from TM1py.Services.ObjectService import ObjectService
from TM1py.Services.SubsetService import SubsetService
from TM1py.Services.HierarchyService import HierarchyService


class DimensionService(ObjectService):
    """ Service to handle Object Updates for TM1 Dimensions
    
    """
    def __init__(self, rest):
        super().__init__(rest)
        self.hierarchies = HierarchyService(rest)
        self.subsets = SubsetService(rest)

    def create(self, dimension):
        """ create a dimension

        :param dimension: instance of TM1py.Dimension
        :return: response
        """
        # If Dimension exists. throw Exception
        if self.exists(dimension.name):
            raise Exception("Dimension already exists")
        # If not all subsequent calls successfull -> undo everything that has been done in this function
        try:
            # create Dimension, Hierarchies, Elements, Edges etc.
            request = "/api/v1/Dimensions"
            response = self._rest.POST(request, dimension.body)
        except TM1pyException as e:
            # undo everything if problem in step 1 or 2
            if self.exists(dimension.name):
                self.delete(dimension.name)
            raise e
        return response

    def get(self, dimension_name):
        """ Get a Dimension

        :param dimension_name:
        :return:
        """
        request = "/api/v1/Dimensions('{}')?$expand=Hierarchies($expand=*)".format(dimension_name)
        dimension_as_json = self._rest.GET(request)
        return Dimension.from_json(dimension_as_json)

    def update(self, dimension):
        """ Update an existing dimension

        :param dimension: instance of TM1py.Dimension
        :return: None
        """
        # update Hierarchies
        for hierarchy in dimension:
            self.hierarchies.update(hierarchy)

    def delete(self, dimension_name):
        """ Delete a dimension

        :param dimension_name: Name of the dimension
        :return:
        """
        request = '/api/v1/Dimensions(\'{}\')'.format(dimension_name)
        return self._rest.DELETE(request)

    def exists(self, dimension_name):
        """ Check if dimension exists
        
        :return: 
        """
        request = "/api/v1/Dimensions('{}')".format(dimension_name)
        return super(DimensionService, self).exists(request)

    def get_all_names(self):
        """Ask TM1 Server for list with all dimension names

        :Returns:
            List of Strings
        """
        response = self._rest.GET('/api/v1/Dimensions?$select=Name', '')
        dimensions = json.loads(response)['value']
        list_dimensions = list(entry['Name'] for entry in dimensions)
        return list_dimensions
