import pytest
from suu.forms.schema import FormDefinition, FormField

@pytest.fixture
def sample_form_def():
    return FormDefinition(
        form_id="test_form",
        url="https://example.com/form",
        description="A test form",
        fields=[
            FormField(name="test_text", selector="#text", type="text", required=True),
            FormField(name="test_select", selector="#select", type="select", options=["A", "B"]),
            FormField(
                name="test_list", 
                type="list", 
                add_button_selector="#add",
                fields=[
                    FormField(name="item_name", selector=".item-name", type="text")
                ]
            )
        ]
    )
