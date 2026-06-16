from pydantic import BaseModel, Field
from typing import List, Optional, Union, Dict, Any, Literal

class FormField(BaseModel):
    name: str = Field(..., description="The internal key for this field in the data dictionary")
    selector: Optional[str] = Field(None, description="The CSS or Playwright selector to find the element")
    type: Literal['text', 'type_text', 'type_and_enter', 'select', 'chosen_select', 'autocomplete', 'file', 'click', 'checkbox', 'list', 'group', 'textarea', 'press_enter'] = Field(..., description="The type of interaction")
    value: Optional[str] = Field(None, description="Static value to use, or if None, use the value from the input data matching 'name'")
    description: Optional[str] = Field(None, description="Description of the field for the AI agent")
    required: bool = Field(True, description="Whether this field is required")
    is_submit: bool = Field(False, description="Whether this field submits the form")
    options: Optional[List[str]] = Field(None, description="Available options for select fields")
    fields: Optional[List["FormField"]] = Field(None, description="Child fields for 'list' or 'group' types")
    list_container_selector: Optional[str] = Field(None, description="Selector for the container of list items (if type='list')")
    add_button_selector: Optional[str] = Field(None, description="Selector for the button to add new items (if type='list')")
    validation_selector: Optional[str] = Field(None, description="Selector that must appear to confirm success (e.g. 'Remove' button)")
    default: Optional[Any] = Field(None, description="Default value to use if input data is missing")

FormField.model_rebuild()

class FormStep(BaseModel):
    name: str = Field(..., description="Name of the step")
    action: str = Field(..., description="Action type: 'navigate', 'fill_field', 'click', 'wait', 'upload'")
    selector: Optional[str] = Field(None, description="Target element selector")
    value: Optional[str] = Field(None, description="Value to input or wait time")
    field_name: Optional[str] = Field(None, description="If filling a field, which field definition to reference")

class FormDefinition(BaseModel):
    form_id: str = Field(..., description="Unique identifier for the form")
    url: str = Field(..., description="The entry URL for the form")
    description: str = Field(..., description="Description of what this form does")
    login_required: bool = Field(False, description="Whether login is required")
    fields: List[FormField] = Field(default_factory=list, description="List of fields available on the form")
    steps: Optional[List[FormStep]] = Field(None, description="Ordered execution steps. If None, simple field filling is assumed.")

class FormConfig(BaseModel):
    forms: List[FormDefinition]
