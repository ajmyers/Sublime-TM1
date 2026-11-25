"""TM1: Put's requests: what it sends TM1 for a process (created or updated) and for rules."""

import json
from urllib.parse import unquote

import httpx2
import pytest

import core_samples
from tm1pkg.core import process_file, rule_file
from tm1pkg.core.connection import Connection, build_client
from tm1pkg.plugin import put

LOGIN = {'Set-Cookie': 'TM1SessionId=abc; Path=/api/'}

# Enough of TM1's $metadata for the client to know it can compile processes and check rules
METADATA = '''<?xml version="1.0" encoding="utf-8"?>
<edmx:Edmx xmlns:edmx="http://docs.oasis-open.org/odata/ns/edmx" Version="4.0"><edmx:DataServices>
<Schema xmlns="http://docs.oasis-open.org/odata/ns/edm" Namespace="ibm.tm1.api.v1" Alias="tm1">
<Annotation Term="Org.OData.Core.V1.SchemaVersion" String="11.8.0"/>
<Action Name="Compile" IsBound="true"><Parameter Name="Process" Type="tm1.Process"/></Action>
<Action Name="CheckRules" IsBound="true"><Parameter Name="Cube" Type="tm1.Cube"/></Action>
<EntityType Name="Process"/><EntityType Name="Cube"/>
<EntityContainer Name="API"><EntitySet Name="Processes" EntityType="tm1.Process"/>
<EntitySet Name="Cubes" EntityType="tm1.Cube"/></EntityContainer>
</Schema></edmx:DataServices></edmx:Edmx>'''


class FakeTm1:
    """Answers Put's requests as TM1 11.8 does, and records the writes: (method, path, body)."""

    def __init__(self, existing=()):
        self.existing, self.writes = set(existing), []

    def __call__(self, request):
        path = unquote(request.url.path).split('/api/v1/', 1)[-1]
        body = json.loads(request.content) if request.content else None
        if request.method == 'GET' and path.startswith("Processes('"):
            name = path[len("Processes('"):-len("')")]
            if name not in self.existing:
                return httpx2.Response(404, json={'error': {'code': '278', 'message': 'not found'}})
            return httpx2.Response(200, json={'Name': name}, headers=LOGIN)
        if path == '$metadata':
            return httpx2.Response(200, text=METADATA, headers={'Content-Type': 'application/xml', **LOGIN})
        if path.endswith(('tm1.Compile', 'tm1.CheckRules')):
            return httpx2.Response(200, json={'value': []}, headers=LOGIN)
        if request.method in ('POST', 'PATCH') and path.startswith(('Processes', 'Cubes')):
            self.writes.append((request.method, path, body))
            return httpx2.Response(201 if request.method == 'POST' else 204, json=body, headers=LOGIN)
        # The login, and the version the client reads to know TM1 can compile and check rules
        return httpx2.Response(200, json={'ID': 1, 'ProductVersion': '11.8.03500.6'}, headers=LOGIN)


def put_with(tm1, work):
    connection = Connection(address='tm1', port='8010', user='admin')
    client = build_client(connection, 'apple', http_client=httpx2.Client(transport=httpx2.MockTransport(tm1)))
    try:
        return work(client)
    finally:
        client.close()


SAMPLES = ['cube_view', 'parameters_and_variables', 'odbc', 'subset', 'no_datasource']


def expected(process):
    """What TM1 is sent for a process: its procedures, data source, parameters and variables. A
    parameter's type isn't sent: TM1 takes it from the value."""
    return {
        'PrologProcedure': process.prolog_procedure, 'MetadataProcedure': process.metadata_procedure,
        'DataProcedure': process.data_procedure, 'EpilogProcedure': process.epilog_procedure,
        'DataSource': {'Type': process.data_source.type, **(process.data_source.model_extra or {})},
        'Parameters': [{'Name': p.name, 'Prompt': p.prompt, 'Value': p.value} for p in process.parameters],
        'Variables': [{'Name': v.name, 'Type': v.type.value, 'Position': v.position, 'StartByte': v.start_byte,
                       'EndByte': v.end_byte} for v in process.variables],
    }


@pytest.mark.parametrize('sample', SAMPLES)
def test_creates_a_new_process_with_what_the_file_holds(sample):
    text = process_file.process_to_text(getattr(core_samples, sample)())
    tm1 = FakeTm1()
    assert put_with(tm1, put.put_process('New One', text)) == []
    process = process_file.text_to_process(text, 'New One')
    assert tm1.writes == [('POST', 'Processes', {'Name': 'New One', **expected(process)})]


@pytest.mark.parametrize('sample', SAMPLES)
def test_patches_an_existing_process_with_what_the_file_holds(sample):
    text = process_file.process_to_text(getattr(core_samples, sample)())
    tm1 = FakeTm1(existing={'Copy Plan'})
    assert put_with(tm1, put.put_process('Copy Plan', text)) == []
    process = process_file.text_to_process(text, 'Copy Plan')
    assert tm1.writes == [('PATCH', "Processes('Copy Plan')", expected(process))]


def test_a_file_without_a_data_source_clears_the_one_on_tm1():
    text = process_file.process_to_text(core_samples.no_datasource())
    tm1 = FakeTm1(existing={'Hello'})
    put_with(tm1, put.put_process('Hello', text))
    assert tm1.writes[0][2]['DataSource'] == {'Type': 'None'}


def test_patches_only_the_rules_of_a_cube():
    text = rule_file.rules_to_text('Sales', ['Region'], "SKIPCHECK;\n['A'] = N: 1;\n")
    tm1 = FakeTm1()
    assert put_with(tm1, put.put_rules('Sales', text)) == []
    assert tm1.writes == [('PATCH', "Cubes('Sales')", {'Rules': rule_file.text_to_rules(text)})]
