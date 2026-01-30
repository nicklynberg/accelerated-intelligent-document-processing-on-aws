# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
import json
import logging
import os
import uuid
from copy import deepcopy
from typing import Optional

from botocore.exceptions import ClientError
from deepdiff import DeepDiff

from idp_common.bda.bda_blueprint_creator import BDABlueprintCreator
from idp_common.config.configuration_manager import ConfigurationManager
from idp_common.config.schema_constants import (
    DEFS_FIELD,
    ID_FIELD,
    REF_FIELD,
    SCHEMA_DESCRIPTION,
    SCHEMA_ITEMS,
    SCHEMA_PROPERTIES,
    SCHEMA_TYPE,
    TYPE_ARRAY,
    TYPE_OBJECT,
    X_AWS_IDP_DOCUMENT_TYPE,
)

logger = logging.getLogger(__name__)


class BdaBlueprintService:
    def __init__(self, dataAutomationProjectArn: Optional[str] = None):
        self.dataAutomationProjectArn = dataAutomationProjectArn
        self.blueprint_creator = BDABlueprintCreator()
        self.blueprint_name_prefix = os.environ.get("STACK_NAME", "")
        self.config_manager = ConfigurationManager()

        return

    def transform_bda_blueprint_to_idp_class_schema(
        self, blueprint_schema: dict
    ) -> dict:
        """
        Transform BDA blueprint schema to IDP class schema format.

        This is the reverse transformation of _transform_json_schema_to_bedrock_blueprint.

        BDA Blueprint Format (input):
        - Uses JSON Schema draft-07
        - Has "definitions" (not "$defs")
        - References use "#/definitions/"
        - Leaf properties have "inferenceType" and "instruction" fields
        - Object/array types do NOT have BDA-specific fields
        - Array properties MUST have "instruction" field

        IDP Class Schema Format (output):
        - Uses JSON Schema draft 2020-12
        - Has "$defs" (not "definitions")
        - References use "#/$defs/"
        - Uses "description" instead of "instruction"
        - No "inferenceType" field

        Args:
            blueprint_schema: BDA blueprint schema in draft-07 format

        Returns:
            IDP class schema in draft 2020-12 format

        Raises:
            ValueError: If blueprint schema is invalid or array properties missing instruction
        """
        if not isinstance(blueprint_schema, dict):
            raise ValueError("Blueprint schema must be a dictionary")

        # Work on a copy to avoid mutating the input
        schema_copy = deepcopy(blueprint_schema)

        # Validate that array properties have instruction field
        self._validate_bda_array_instruction_requirements(schema_copy)

        # Create base IDP schema structure
        idp_schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": schema_copy.get("class", "Document"),
            "x-aws-idp-document-type": schema_copy.get("class", "Document"),
            "type": "object",
        }

        # Add description if present
        if "description" in schema_copy:
            idp_schema["description"] = schema_copy["description"]

        # Transform definitions to $defs
        if "definitions" in schema_copy:
            idp_schema["$defs"] = {}
            for def_name, def_value in schema_copy["definitions"].items():
                idp_schema["$defs"][def_name] = self._transform_bda_definition_to_idp(
                    def_value
                )

        # Transform properties
        if "properties" in schema_copy:
            idp_schema["properties"] = {}
            for prop_name, prop_value in schema_copy["properties"].items():
                idp_schema["properties"][prop_name] = (
                    self._transform_bda_property_to_idp(prop_value)
                )

        return idp_schema

    def _validate_bda_array_instruction_requirements(
        self, blueprint_schema: dict
    ) -> None:
        """
        Validate that all array properties in BDA blueprint have the required 'instruction' field.

        Args:
            blueprint_schema: BDA blueprint schema to validate (works in-place on the copy)

        Raises:
            ValueError: If any array property is missing the 'instruction' field
        """

        def validate_properties(properties: dict, path: str = ""):
            """Recursively validate properties for array instruction requirements."""
            for prop_name, prop_value in properties.items():
                current_path = f"{path}.{prop_name}" if path else prop_name

                if not isinstance(prop_value, dict):
                    continue

                # Check if this is an array property
                if prop_value.get("type") == "array":
                    # Array properties must have instruction field
                    if "instruction" not in prop_value:
                        prop_value["instruction"] = "-"  # default it

                # Recursively check nested object properties
                if prop_value.get("type") == "object" and "properties" in prop_value:
                    validate_properties(prop_value["properties"], current_path)

        # Validate main properties
        if "properties" in blueprint_schema:
            validate_properties(blueprint_schema["properties"])

        # Validate definitions properties
        definitions = blueprint_schema.get("definitions", {})
        for def_name, def_value in definitions.items():
            if isinstance(def_value, dict) and "properties" in def_value:
                validate_properties(def_value["properties"], f"definitions.{def_name}")

    def _transform_bda_definition_to_idp(self, definition: dict) -> dict:
        """
        Transform a BDA definition to IDP format.

        Args:
            definition: BDA definition schema

        Returns:
            IDP definition schema
        """
        if not isinstance(definition, dict):
            return definition

        result = deepcopy(definition)

        # Transform properties if present
        if "properties" in result:
            transformed_properties = {}
            for prop_name, prop_value in result["properties"].items():
                transformed_properties[prop_name] = self._transform_bda_property_to_idp(
                    prop_value
                )
            result["properties"] = transformed_properties

        return result

    def _transform_bda_property_to_idp(self, property_schema: dict) -> dict:
        """
        Transform a BDA property to IDP format.

        Args:
            property_schema: BDA property schema

        Returns:
            IDP property schema
        """
        if not isinstance(property_schema, dict):
            return property_schema

        result = deepcopy(property_schema)

        # Handle $ref properties - convert definitions to $defs
        if "$ref" in result:
            result["$ref"] = result["$ref"].replace("/definitions/", "/$defs/")
            return result

        # Convert BDA-specific fields to IDP format
        if "instruction" in result:
            # Convert instruction to description
            result["description"] = result.pop("instruction")

        # Remove BDA-specific fields
        if "inferenceType" in result:
            result.pop("inferenceType")

        # Handle array items
        if result.get("type") == "array" and "items" in result:
            result["items"] = self._transform_bda_property_to_idp(result["items"])

        # Handle object properties
        if result.get("type") == "object" and "properties" in result:
            transformed_properties = {}
            for prop_name, prop_value in result["properties"].items():
                transformed_properties[prop_name] = self._transform_bda_property_to_idp(
                    prop_value
                )
            result["properties"] = transformed_properties

        return result

    def _retrieve_all_blueprints(self, project_arn: str):
        """
        Retrieve all blueprints from the Bedrock Data Automation service.
        If project_arn is provided, retrieves blueprints associated with that project.

        Args:
            project_arn (Optional[str]): ARN of the data automation project to filter blueprints

        Returns:
            list: List of blueprint names and ARNs
        """
        try:
            all_blueprints = []

            # If project ARN is provided, get blueprints from the project
            if project_arn:
                try:
                    blueprint_response = self.blueprint_creator.list_blueprints(
                        projectArn=project_arn, projectStage="LIVE"
                    )

                    blueprints = blueprint_response.get("blueprints", [])
                    for blueprint in blueprints:
                        blueprint_arn = blueprint.get("blueprintArn", None)
                        if "aws:blueprint" in blueprint_arn:
                            continue
                        response = self.blueprint_creator.get_blueprint(
                            blueprint_arn=blueprint_arn, stage="LIVE"
                        )
                        _blueprint = response.get("blueprint")
                        # Add blueprintVersion with default if missing
                        _blueprint["blueprintVersion"] = blueprint.get(
                            "blueprintVersion", "1"
                        )
                        all_blueprints.append(_blueprint)
                    logger.info(
                        f"{len(all_blueprints)} blueprints retrieved for {project_arn}"
                    )
                    logger.info(
                        f"blueprints retrieved {json.dumps(all_blueprints, default=str)}"
                    )
                    return all_blueprints

                except ClientError as e:
                    logger.warning(f"Could not retrieve project {project_arn}: {e}")
                    # Fall through to list all blueprints
                    return []

        except Exception as e:
            logger.error(f"Error retrieving blueprints: {e}")
            return []

    def _transform_json_schema_to_bedrock_blueprint(self, json_schema: dict) -> dict:
        """
        Transform JSON Schema (draft 2020-12) to BDA blueprint format (draft-07).

        Handles two input patterns:
        1. Schemas with $defs (from migration.py)
        2. Flat nested schemas (from classes_discovery.py)

        BDA requirements based on working schemas:
        - Uses "definitions" (not "$defs") - JSON Schema draft-07
        - References use "#/definitions/" (not "#/$defs/")
        - Only LEAF properties get "inferenceType" and "instruction"
        - Object/array types do NOT get these fields
        - Array properties MUST have "instruction" field

        Args:
            json_schema: JSON Schema from configuration

        Returns:
            Blueprint schema in BDA-compatible draft-07 format

        Raises:
            ValueError: If array properties are missing required instruction field
        """
        # Work on a deep copy to avoid mutating the input
        schema_copy = deepcopy(json_schema)

        # Validate array properties have instruction field
        self._validate_array_instruction_requirements(schema_copy)

        blueprint = self._create_base_blueprint_structure(schema_copy)

        defs = schema_copy.get(DEFS_FIELD, {})
        properties = schema_copy.get(SCHEMA_PROPERTIES, {})

        if defs:
            blueprint.update(self._process_schema_with_defs(defs, properties))
        else:
            blueprint.update(self._process_flat_schema(properties))

        return blueprint

    def _validate_array_instruction_requirements(self, json_schema: dict) -> None:
        """
        Ensure that all array properties have the required 'instruction' field.
        If not present, this will default it to "-" during transformation.

        BDA requires all array properties to have an 'instruction' field for proper
        blueprint creation. This method ensures compliance by defaulting missing instructions.

        Args:
            json_schema: JSON Schema to validate and update (works in-place on the copy)

        Note: This method works in-place on the provided schema (which should be a copy).
        """

        def add_missing_instructions(properties: dict, path: str = ""):
            """Recursively add missing instruction fields to array properties."""
            for prop_name, prop_value in properties.items():
                current_path = f"{path}.{prop_name}" if path else prop_name

                if not isinstance(prop_value, dict):
                    continue

                # Check if this is an array property
                if prop_value.get("type") == "array":
                    # Array properties must have instruction field - default to "-" if missing
                    if (
                        "instruction" not in prop_value
                        and "description" not in prop_value
                    ):
                        prop_value["instruction"] = "-"
                    elif (
                        "description" in prop_value and "instruction" not in prop_value
                    ):
                        # Use description as instruction if available
                        prop_value["instruction"] = prop_value["description"]

                # Recursively check nested object properties
                if prop_value.get("type") == "object" and "properties" in prop_value:
                    add_missing_instructions(prop_value["properties"], current_path)

        # Add missing instructions to main properties
        if "properties" in json_schema:
            add_missing_instructions(json_schema["properties"])

        # Add missing instructions to $defs properties
        defs = json_schema.get("$defs", {})
        for def_name, def_value in defs.items():
            if isinstance(def_value, dict) and "properties" in def_value:
                add_missing_instructions(def_value["properties"], f"$defs.{def_name}")

    def _create_base_blueprint_structure(self, json_schema: dict) -> dict:
        """Create the base blueprint structure."""
        return {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "class": json_schema.get(
                ID_FIELD, json_schema.get(X_AWS_IDP_DOCUMENT_TYPE, "Document")
            ),
            "description": json_schema.get(
                SCHEMA_DESCRIPTION, "Document schema for data extraction"
            ),
            "type": TYPE_OBJECT,
        }

    def _process_schema_with_defs(self, defs: dict, properties: dict) -> dict:
        """Process schema that has $defs (Pattern 1: from migration.py)."""
        result = {"definitions": {}, "properties": {}}

        # Process definitions
        for def_name, def_value in defs.items():
            result["definitions"][def_name] = self._add_bda_fields_to_schema(def_value)

        # Process properties and update $ref paths
        for prop_name, prop_value in properties.items():
            if REF_FIELD in prop_value:
                # $ref properties should have instruction: "-" based on correct_format.json
                result["properties"][prop_name] = {
                    REF_FIELD: self._normalize_ref_path(prop_value[REF_FIELD]),
                    "instruction": "-",
                }
            else:
                result["properties"][prop_name] = self._add_bda_fields_to_schema(
                    prop_value
                )

        return result

    def _process_flat_schema(self, properties: dict) -> dict:
        """Process flat nested schema (Pattern 2: from classes_discovery.py)."""
        simple_properties, extracted_definitions = self._extract_complex_objects(
            properties
        )

        result = {"properties": {}}

        # Add definitions if any were extracted
        if extracted_definitions:
            result["definitions"] = {}
            for def_name, def_value in extracted_definitions.items():
                result["definitions"][def_name] = self._add_bda_fields_to_schema(
                    def_value
                )

        # Transform simple properties
        for prop_name, prop_value in simple_properties.items():
            if REF_FIELD in prop_value:
                # This is a $ref to an extracted definition
                result["properties"][prop_name] = {REF_FIELD: prop_value[REF_FIELD]}
            else:
                # Handle arrays and simple properties
                prop_type = prop_value.get(SCHEMA_TYPE, "string")
                if prop_type == TYPE_ARRAY and SCHEMA_ITEMS in prop_value:
                    result["properties"][prop_name] = (
                        self._process_array_property_simple(prop_value)
                    )
                else:
                    result["properties"][prop_name] = self._add_bda_fields_to_schema(
                        prop_value
                    )

        return result

    def _normalize_ref_path(self, ref_path: str) -> str:
        """Convert $defs references to definitions references."""
        return ref_path.replace("/$defs/", "/definitions/")

    def _add_bda_fields_to_leaf_property(
        self, prop_schema: dict, original_description: str = None
    ) -> dict:
        """Add BDA fields (inferenceType, instruction) to a leaf property."""
        result = {
            "type": prop_schema.get(SCHEMA_TYPE, "string"),
            "inferenceType": prop_schema.get("inferenceType", "explicit"),
        }

        if "instruction" in prop_schema:
            result["instruction"] = prop_schema["instruction"]
        elif original_description:
            result["instruction"] = original_description
        else:
            result["instruction"] = "Extract this field from the document"

        return result

    def _process_object_properties(self, properties: dict) -> dict:
        """
        Process object properties, adding BDA fields to leaf properties only.

        BDA Limitations (as of current version):
        - Nested objects are not supported
        - Nested arrays (arrays within object definitions) are not supported

        TODO: When BDA supports nested structures, re-enable processing of:
        - TYPE_OBJECT properties with nested properties
        - TYPE_ARRAY properties within object definitions
        """
        processed_properties = {}

        for name, value in properties.items():
            # Skip $ref properties
            if REF_FIELD in value:
                continue

            # Skip nested objects - BDA doesn't support them
            # TODO: Re-enable when BDA supports nested objects
            if value.get(SCHEMA_TYPE) == TYPE_OBJECT:
                logger.info(
                    f"Skipping nested object property '{name}' - not supported by BDA"
                )
                continue

            # Skip nested arrays - BDA doesn't support arrays within object definitions
            # TODO: Re-enable when BDA supports nested arrays within objects
            if value.get(SCHEMA_TYPE) == TYPE_ARRAY:
                logger.info(
                    f"Skipping nested array property '{name}' - not supported by BDA"
                )
                continue

            # Process leaf property (non-array, non-object)
            processed_properties[name] = self._add_bda_fields_to_leaf_property(
                value, value.get(SCHEMA_DESCRIPTION)
            )

        return processed_properties

    def _process_array_property_simple(self, prop_value: dict) -> dict:
        """Process array properties for simple cases."""
        items = prop_value[SCHEMA_ITEMS]
        if isinstance(items, dict) and REF_FIELD in items:
            # Array with $ref items - preserve array description as instruction
            array_property = {
                SCHEMA_TYPE: TYPE_ARRAY,
                SCHEMA_ITEMS: {REF_FIELD: items[REF_FIELD]},
            }
            # Ensure instruction field is present
            if "instruction" in prop_value:
                array_property["instruction"] = prop_value["instruction"]
            elif SCHEMA_DESCRIPTION in prop_value:
                array_property["instruction"] = prop_value[SCHEMA_DESCRIPTION]
            else:
                # Default instruction to "-" if not present
                array_property["instruction"] = "-"
            return array_property
        else:
            # Array with simple items - ensure instruction field is added but NO inferenceType
            result = self._add_bda_fields_to_schema(prop_value)
            # Ensure array has instruction field but remove inferenceType if present
            if result.get(SCHEMA_TYPE) == TYPE_ARRAY:
                if "instruction" not in result:
                    if SCHEMA_DESCRIPTION in prop_value:
                        result["instruction"] = prop_value[SCHEMA_DESCRIPTION]
                    else:
                        result["instruction"] = "-"
                # Arrays should not have inferenceType
                result.pop("inferenceType", None)
            return result

    def _process_array_property(
        self, prop_name: str, prop_value: dict, extracted_definitions: dict
    ) -> dict:
        """
        Process array properties, extracting complex item types to definitions.

        BDA Limitations (as of current version):
        - Arrays with complex nested object items are not supported if those objects contain nested structures

        TODO: When BDA supports nested structures, re-enable processing of complex nested array items.
        """
        items = prop_value.get(SCHEMA_ITEMS, {})

        if (
            isinstance(items, dict)
            and items.get(SCHEMA_TYPE) == TYPE_OBJECT
            and SCHEMA_PROPERTIES in items
        ):
            # Check if the array item object has nested complex structures
            if self._has_nested_complex_structures(items[SCHEMA_PROPERTIES]):
                # Skip arrays with complex nested item structures
                logger.info(
                    f"Skipping array property '{prop_name}' with complex nested item structures - not supported by BDA"
                )
                # Return a simple array property with instruction but no items processing
                result = {
                    SCHEMA_TYPE: TYPE_ARRAY,
                    "instruction": prop_value.get(SCHEMA_DESCRIPTION, "-"),
                }
                return result

            # Array of simple objects - extract to definition
            item_def_name = f"{prop_name}Item"

            item_definition = {
                SCHEMA_TYPE: TYPE_OBJECT,
                SCHEMA_PROPERTIES: self._process_object_properties(
                    items[SCHEMA_PROPERTIES]
                ),
            }

            if SCHEMA_DESCRIPTION in items:
                item_definition[SCHEMA_DESCRIPTION] = items[SCHEMA_DESCRIPTION]

            extracted_definitions[item_def_name] = item_definition

            # Return array with $ref to definition
            array_property = {
                SCHEMA_TYPE: TYPE_ARRAY,
                SCHEMA_ITEMS: {REF_FIELD: f"#/definitions/{item_def_name}"},
            }

            # Ensure instruction field is present
            if "instruction" in prop_value:
                array_property["instruction"] = prop_value["instruction"]
            elif SCHEMA_DESCRIPTION in prop_value:
                array_property["instruction"] = prop_value[SCHEMA_DESCRIPTION]
            else:
                # Default instruction to "-" if not present
                array_property["instruction"] = "-"

            return array_property
        else:
            # Array of simple items - ensure instruction field is added
            result = deepcopy(prop_value)
            if result.get(SCHEMA_TYPE) == TYPE_ARRAY and "instruction" not in result:
                if SCHEMA_DESCRIPTION in result:
                    result["instruction"] = result[SCHEMA_DESCRIPTION]
                else:
                    result["instruction"] = "-"
            return result

    def _extract_complex_objects(self, properties: dict) -> tuple[dict, dict]:
        """
        Extract complex objects from flat nested schema properties.

        BDA Limitations (as of current version):
        - Nested objects within objects are not supported
        - Nested arrays within objects are not supported

        This method will skip complex nested structures that BDA cannot handle.
        TODO: When BDA supports nested structures, re-enable extraction of complex nested objects.

        Args:
            properties: Properties dict from flat nested schema

        Returns:
            tuple: (simple_properties, extracted_definitions)
                - simple_properties: Properties with complex objects replaced by $ref
                - extracted_definitions: Complex objects extracted to definitions
        """
        simple_properties = {}
        extracted_definitions = {}

        for prop_name, prop_value in properties.items():
            if not isinstance(prop_value, dict):
                simple_properties[prop_name] = prop_value
                continue

            prop_type = prop_value.get(SCHEMA_TYPE, "string")

            if prop_type == TYPE_OBJECT and SCHEMA_PROPERTIES in prop_value:
                # Check if this object has nested complex structures
                has_nested_complex = self._has_nested_complex_structures(
                    prop_value[SCHEMA_PROPERTIES]
                )

                if has_nested_complex:
                    # Skip objects with nested complex structures - BDA doesn't support them
                    logger.info(
                        f"Skipping complex object property '{prop_name}' with nested structures - not supported by BDA"
                    )
                    continue

                # This is a simple object - extract to definitions
                definition_name = prop_name

                # Create the definition for this object
                object_definition = {
                    SCHEMA_TYPE: TYPE_OBJECT,
                    SCHEMA_PROPERTIES: self._process_object_properties(
                        prop_value[SCHEMA_PROPERTIES]
                    ),
                }

                # Preserve description if present
                if SCHEMA_DESCRIPTION in prop_value:
                    object_definition[SCHEMA_DESCRIPTION] = prop_value[
                        SCHEMA_DESCRIPTION
                    ]

                extracted_definitions[definition_name] = object_definition

                # Replace with $ref in simple properties
                simple_properties[prop_name] = {
                    REF_FIELD: f"#/definitions/{definition_name}"
                }

            elif prop_type == TYPE_ARRAY and SCHEMA_ITEMS in prop_value:
                # Check if array items are complex objects with nested structures
                items = prop_value.get(SCHEMA_ITEMS, {})
                if (
                    isinstance(items, dict)
                    and items.get(SCHEMA_TYPE) == TYPE_OBJECT
                    and SCHEMA_PROPERTIES in items
                    and self._has_nested_complex_structures(items[SCHEMA_PROPERTIES])
                ):
                    # Skip arrays with complex nested item structures
                    logger.info(
                        f"Skipping array property '{prop_name}' with complex nested item structures - not supported by BDA"
                    )
                    continue

                # Handle arrays using the dedicated array processor
                simple_properties[prop_name] = self._process_array_property(
                    prop_name, prop_value, extracted_definitions
                )
            else:
                # Simple property - keep as is
                simple_properties[prop_name] = prop_value

        return simple_properties, extracted_definitions

    def _has_nested_complex_structures(self, properties: dict) -> bool:
        """
        Check if properties contain nested complex structures (objects or arrays).

        BDA doesn't support:
        - Objects within objects
        - Arrays within objects

        Args:
            properties: Properties dict to check

        Returns:
            bool: True if nested complex structures are found
        """
        for prop_name, prop_value in properties.items():
            if not isinstance(prop_value, dict):
                continue

            prop_type = prop_value.get(SCHEMA_TYPE, "string")

            # Check for nested objects
            if prop_type == TYPE_OBJECT:
                logger.debug(f"Found nested object property '{prop_name}'")
                return True

            # Check for nested arrays
            if prop_type == TYPE_ARRAY:
                logger.debug(f"Found nested array property '{prop_name}'")
                return True

        return False

    def _add_bda_fields_to_schema(self, schema: dict) -> dict:
        """
        Add BDA fields (inferenceType, instruction) ONLY to leaf properties.
        Ensure array properties have instruction field but NOT inferenceType.

        Critical BDA requirements (based on working schemas):
        - Pure $ref properties: ONLY the $ref field (when inside definitions)
        - Object/array types: ONLY type and properties (NO description, inferenceType)
        - Array types: MUST have instruction field but NO inferenceType
        - Leaf types: type, inferenceType, instruction (NO description)

        Args:
            schema: Property or definition schema

        Returns:
            Schema with BDA fields, description removed
        """
        if not isinstance(schema, dict):
            return schema

        # Make deep copy to avoid mutation
        result = deepcopy(schema)

        # Remove description field - BDA doesn't use it (only instruction)
        original_description = result.pop(SCHEMA_DESCRIPTION, None)

        prop_type = result.get(SCHEMA_TYPE, "string")

        # Add BDA fields ONLY for leaf/primitive types
        if prop_type not in [TYPE_OBJECT, TYPE_ARRAY]:
            # This is a leaf property - use the dedicated helper
            return self._add_bda_fields_to_leaf_property(result, original_description)

        # Handle object types - process properties using helper method
        if prop_type == TYPE_OBJECT and SCHEMA_PROPERTIES in result:
            result[SCHEMA_PROPERTIES] = self._process_object_properties(
                result[SCHEMA_PROPERTIES]
            )

        # Handle array items (but don't add BDA fields to the array itself)
        if prop_type == TYPE_ARRAY and SCHEMA_ITEMS in result:
            # Special handling for $ref items - preserve the $ref structure
            items = result[SCHEMA_ITEMS]
            if isinstance(items, dict) and REF_FIELD in items:
                # For $ref items, just normalize the path and preserve the structure
                result[SCHEMA_ITEMS] = {
                    REF_FIELD: self._normalize_ref_path(items[REF_FIELD])
                }
            else:
                # For non-$ref items, process recursively
                result[SCHEMA_ITEMS] = self._add_bda_fields_to_schema(
                    result[SCHEMA_ITEMS]
                )

            # Ensure array has instruction field but NO inferenceType
            if "instruction" not in result:
                if original_description:
                    result["instruction"] = original_description
                else:
                    result["instruction"] = "-"

            # Remove inferenceType if it was added (arrays should not have it)
            result.pop("inferenceType", None)

        return result

    def _check_for_updates(self, custom_class: dict, blueprint: dict):
        """
        Check if the custom_class JSON Schema differs from the existing blueprint.
        Transform both to Bedrock format and then compare.
        """
        # Parse the blueprint schema
        blueprint_schema = blueprint["schema"]
        if isinstance(blueprint_schema, str):
            blueprint_schema = json.loads(blueprint_schema)

        # Transform the custom_class to Bedrock format for comparison
        transformed_custom = self._transform_json_schema_to_bedrock_blueprint(
            custom_class
        )

        # Use DeepDiff to compare the schemas
        diff = DeepDiff(blueprint_schema, transformed_custom, ignore_order=True)

        updates_found = bool(diff)

        if updates_found:
            logger.info("Schema changes detected between custom class and blueprint")
            # Log specific differences for debugging
            logger.info(f"Differences found: {diff}")

        return updates_found

    def _blueprint_lookup(self, existing_blueprints, doc_class):
        # Create a lookup dictionary for existing blueprints by name prefix
        _blueprint_prefix = f"{self.blueprint_name_prefix}-{doc_class}"
        logger.info(f"blueprint lookup using name {_blueprint_prefix}")
        for blueprint in existing_blueprints:
            blueprint_name = blueprint.get("blueprintName", "")
            if blueprint_name.startswith(_blueprint_prefix):
                return blueprint
        return None

    def create_blueprints_from_custom_configuration(self):
        """
        Create blueprint from custom configurations.
        Raises:
            Exception: If blueprint creation fails
        """
        logger.info("Creating blueprint for document ")

        try:
            config_item = self.config_manager.get_configuration(config_type="Config")

            # Type check: Config configuration should return IDPConfig which has classes attribute
            if not config_item:
                logger.info("No Config configuration to process")
                return {"status": "success", "message": "No classes to process"}

            # Use getattr to safely access classes attribute
            classess = getattr(config_item, "classes", None)

            if not classess or len(classess) == 0:
                logger.info("No Config configuration to process")
                return {"status": "success", "message": "No classes to process"}

            # At this point, classess is guaranteed to be non-None and non-empty
            assert classess is not None, "classess should not be None after validation"

            classess_status = []
            # retrieve all blueprints for this project.
            existing_blueprints = self._retrieve_all_blueprints(
                self.dataAutomationProjectArn
            )
            if not existing_blueprints:
                existing_blueprints = []

            classess_added = []
            # check for blueprints which doesn't have an IDP class definition
            # create class definitions and save
            for bda_blueprint in existing_blueprints:
                blueprint_name = bda_blueprint.get("blueprintName", "")
                docu_class_exists = False
                for custom_class in classess:
                    docu_class = custom_class.get(
                        ID_FIELD, custom_class.get(X_AWS_IDP_DOCUMENT_TYPE, "")
                    )
                    if docu_class in blueprint_name:
                        docu_class_exists = True
                        break
                logger.info(
                    f"Blueprint {blueprint_name} class exists {docu_class_exists}"
                )
                if not docu_class_exists:
                    # docu class doesn't exists
                    # create IDP doc class from blueprint
                    blueprint_schema = bda_blueprint["schema"]
                    if isinstance(blueprint_schema, str):
                        blueprint_schema = json.loads(blueprint_schema)

                    # Transform BDA blueprint to IDP class schema
                    idp_class_schema = self.transform_bda_blueprint_to_idp_class_schema(
                        blueprint_schema
                    )
                    docu_class = idp_class_schema.get(
                        ID_FIELD, custom_class.get(X_AWS_IDP_DOCUMENT_TYPE, "")
                    )
                    # Add the new class to the classes list
                    classess_added.append(idp_class_schema)
                    blueprint_arn = bda_blueprint.get("blueprintArn", "")
                    classess_status.append(
                        {
                            "class": docu_class,
                            "blueprint_arn": blueprint_arn,
                            "status": "success",
                        }
                    )

                    logger.info(
                        f"Created IDP class schema from blueprint {blueprint_name}"
                    )

            blueprints_updated = []

            for custom_class in classess:
                try:
                    blueprint_arn = custom_class.get("blueprint_arn", None)
                    blueprint_name = custom_class.get("blueprint_name", None)
                    docu_class = custom_class.get(
                        ID_FIELD, custom_class.get(X_AWS_IDP_DOCUMENT_TYPE, "")
                    )

                    blueprint_exists = self._blueprint_lookup(
                        existing_blueprints, docu_class
                    )
                    if blueprint_exists:
                        blueprint_arn = blueprint_exists.get("blueprintArn")
                        blueprint_name = blueprint_exists.get("blueprintName")
                        logger.info(
                            f"blueprint already exists for this class {docu_class} updating blueprint {blueprint_arn}"
                        )

                    if blueprint_arn:
                        # Use existing blueprint
                        # Note: We don't modify custom_class since it's a JSON Schema
                        logger.info(
                            f"Found existing blueprint for class {docu_class}: {blueprint_name}"
                        )
                        blueprints_updated.append(blueprint_arn)

                        # Check for updates on existing blueprint
                        if self._check_for_updates(
                            custom_class=custom_class, blueprint=blueprint_exists
                        ):
                            blueprint_schema = (
                                self._transform_json_schema_to_bedrock_blueprint(
                                    custom_class
                                )
                            )
                            logger.info(
                                f"Blueprint schema generate:: for {docu_class} to update"
                            )
                            logger.info(json.dumps(blueprint_schema, indent=2))
                            logger.info("Blueprint schema generate:: END")

                            result = self.blueprint_creator.update_blueprint(
                                blueprint_arn=blueprint_arn,
                                stage="LIVE",
                                schema=json.dumps(blueprint_schema),
                            )
                            result = self.blueprint_creator.create_blueprint_version(
                                blueprint_arn=blueprint_arn,
                                project_arn=self.dataAutomationProjectArn,
                            )
                            # Note: We don't store blueprint_version in custom_class since it's a JSON Schema
                            logger.info(
                                f"Updated existing blueprint for class {docu_class}"
                            )
                        else:
                            logger.info(
                                f"No updates needed for existing blueprint {blueprint_name}"
                            )

                    else:
                        # create new blueprint
                        # Call the create_blueprint method
                        blueprint_name = f"{self.blueprint_name_prefix}-{docu_class}-{uuid.uuid4().hex[:8]}"

                        blueprint_schema = (
                            self._transform_json_schema_to_bedrock_blueprint(
                                custom_class
                            )
                        )
                        logger.info(
                            f"Blueprint schema generate:: for {docu_class} for create"
                        )
                        logger.info("Blueprint schema generate:: END")

                        result = self.blueprint_creator.create_blueprint(
                            document_type="DOCUMENT",
                            blueprint_name=blueprint_name,
                            schema=json.dumps(blueprint_schema),
                        )
                        status = result["status"]
                        logger.info(f"blueprint created status {status}")
                        if status != "success":
                            raise Exception(f"Failed to create blueprint: {result}")

                        blueprint_arn = result["blueprint"]["blueprintArn"]
                        blueprint_name = result["blueprint"]["blueprintName"]
                        # Note: We don't store blueprint metadata in custom_class since it's a JSON Schema
                        # update the project or create new project
                        # update the project with version
                        result = self.blueprint_creator.create_blueprint_version(
                            blueprint_arn=blueprint_arn,
                            project_arn=self.dataAutomationProjectArn,
                        )
                        blueprints_updated.append(blueprint_arn)
                        logger.info(
                            f"Created new blueprint for class {docu_class}: {blueprint_name}"
                        )
                    classess_status.append(
                        {
                            "class": docu_class,  # Use the docu_class we extracted earlier
                            "blueprint_arn": blueprint_arn,
                            "status": "success",
                        }
                    )

                except Exception as e:
                    class_name = (
                        custom_class.get(
                            ID_FIELD,
                            custom_class.get(X_AWS_IDP_DOCUMENT_TYPE, "unknown"),
                        )
                        if custom_class
                        else "unknown"
                    )
                    logger.error(
                        f"Error processing blueprint creation/update for class {class_name}: {e}"
                    )
                    classess_status.append(
                        {
                            "class": class_name,
                            "status": "failed",
                            "error_message": f"Exception - {str(e)}",
                        }
                    )
            self._synchronize_deletes(
                existing_blueprints=existing_blueprints,
                blueprints_updated=blueprints_updated,
            )
            # add the new class if any
            if len(classess_added) > 0:
                classess.extend(classess_added)
            self.config_manager.handle_update_custom_configuration(
                {"classes": classess}
            )

            return classess_status

        except Exception as e:
            logger.error(f"Error processing blueprint creation: {e}", exc_info=True)
            # Re-raise the exception to be handled by the caller
            raise Exception(f"Failed to process blueprint creation: {str(e)}")

    def _synchronize_deletes(self, existing_blueprints, blueprints_updated):
        # remove all blueprints which are not in custom class
        blueprints_to_delete = []
        blueprints_arn_to_delete = []
        for blueprint in existing_blueprints:
            blueprint_name = blueprint.get("blueprintName", "")
            blueprint_arn = blueprint.get("blueprintArn", "")
            blueprint_version = blueprint.get("blueprintVersion", "")
            if blueprint_arn in blueprints_updated:
                continue
            if blueprint_name.startswith(self.blueprint_name_prefix):
                # delete detected - remove the blueprint
                logger.info(f"deleting blueprint not in custom class {blueprint_name}")
                blueprints_to_delete.append(blueprint)
                blueprints_arn_to_delete.append(blueprint_arn)

        if len(blueprints_to_delete) > 0:
            # remove the blueprints marked for deletion for the project first before deleting them.
            response = self.blueprint_creator.list_blueprints(
                self.dataAutomationProjectArn, "LIVE"
            )
            custom_configurations = response.get("blueprints", [])
            new_custom_configurations = []
            for custom_blueprint in custom_configurations:
                if custom_blueprint.get("blueprintArn") not in blueprints_arn_to_delete:
                    new_custom_configurations.append(custom_blueprint)
            new_custom_configurations = {"blueprints": new_custom_configurations}
            response = self.blueprint_creator.update_project_with_custom_configurations(
                self.dataAutomationProjectArn,
                customConfiguration=new_custom_configurations,
            )

            try:
                for _blueprint_delete in blueprints_to_delete:
                    self.blueprint_creator.delete_blueprint(
                        _blueprint_delete.get("blueprintArn"),
                        _blueprint_delete.get("blueprintVersion"),
                    )
            except Exception:
                logger.error(
                    f"Error during deleting blueprint {blueprint_name} {blueprint_arn} {blueprint_version}"
                )
            try:
                for _blueprint_delete in blueprints_to_delete:
                    self.blueprint_creator.delete_blueprint(
                        _blueprint_delete.get("blueprintArn"), None
                    )
            except Exception:
                logger.error(
                    f"Error during deleting blueprint {blueprint_name} {blueprint_arn} {blueprint_version}"
                )
