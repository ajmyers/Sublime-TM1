"""The Turbo Integrator formatter (format on save, and TM1: Format)."""

from pelle.Format import format_procedure


def test_upper_cases_functions_and_spaces_operators():
    assert format_procedure("nX=cellgetn('Sales',sRegion)+1;") == "nX = CELLGETN('Sales', sRegion) + 1;"


def test_indents_blocks():
    text = "nX=1;\nif(nX>0);\nwhile(nY<3);\nnY=nY+1;\nend;\nelse;\nnX=0;\nendif;"
    assert format_procedure(text) == (
        'nX = 1;\n'
        'IF(nX > 0);\n'
        '   WHILE(nY < 3);\n'
        '      nY = nY + 1;\n'
        '   END;\n'
        'ELSE;\n'
        '   nX = 0;\n'
        'ENDIF;'
    )


def test_leaves_strings_and_comments_alone():
    text = "# keep   this   comment\nsMsg='a  +  b';"
    assert format_procedure(text) == "# keep   this   comment\nsMsg = 'a  +  b';"


def test_corrects_the_case_of_ti_variables():
    assert format_procedure('nX=datasourcetype;') == 'nX = DatasourceType;'


def test_formats_the_first_word_of_a_procedure():
    assert format_procedure('if(nX>0);\nnX=0;\nendif;') == 'IF(nX > 0);\n   nX = 0;\nENDIF;'
    assert format_procedure('datasourcetype=1;') == 'DatasourceType = 1;'
    assert format_procedure("executeprocess('Archive');") == "EXECUTEPROCESS('Archive');"


def test_formats_the_last_word_of_a_procedure():
    assert format_procedure('nX=1;\nprocessquit') == 'nX = 1;\nPROCESSQUIT'


def test_splits_long_executeprocess_calls():
    text = "nX=1;\nExecuteProcess('Load Sales','pYear','2024','pScale',1000);"
    assert format_procedure(text) == (
        'nX = 1;\n'
        "EXECUTEPROCESS('Load Sales'\n"
        "   , 'pYear', '2024'\n"
        "   , 'pScale', 1000\n"
        ");"
    )


def test_is_idempotent():
    text = "if(nX>0);\nnX=cellgetn('Sales',sRegion)+1;\nendif;"
    once = format_procedure(text)
    assert format_procedure(once) == once
