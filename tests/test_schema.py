import pytest
from suu.forms.schema import FormDefinition, FormField
from pydantic import ValidationError

def test_form_definition_validation(sample_form_def):
    """Test valid form definition creation."""
    assert sample_form_def.form_id == "test_form"
    assert len(sample_form_def.fields) == 3

def test_invalid_field_type():
    """Test that invalid field types raise validation error."""
    with pytest.raises(ValidationError):
        FormField(name="bad", selector="#bad", type="invalid_type")

def test_list_field_structure():
    """Test list field structure validation."""
    field = FormField(
        name="my_list",
        type="list",
        add_button_selector="#add",
        fields=[FormField(name="child", selector=".child", type="text")]
    )
    assert field.type == "list"
    assert len(field.fields) == 1
