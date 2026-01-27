// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import React, { useState, useEffect, useRef, useMemo } from 'react';
import {
  Container,
  Header,
  SpaceBetween,
  Box,
  Button,
  Alert,
  Spinner,
  Form,
  SegmentedControl,
  Modal,
  FormField,
  Input,
  RadioGroup,
  Icon,
  Badge,
} from '@cloudscape-design/components';
import Editor from '@monaco-editor/react';
// eslint-disable-next-line import/no-extraneous-dependencies
import yaml from 'js-yaml';
import ReactMarkdown from 'react-markdown';
import { generateClient } from 'aws-amplify/api';
import { ConsoleLogger } from 'aws-amplify/utils';
import useConfigurationVersions from '../../hooks/use-configuration-versions';
import useConfigurationLibrary from '../../hooks/use-configuration-library';
import useSettingsContext from '../../contexts/settings';
import ConfigBuilder from './ConfigBuilder';
import ConfigurationVersionsTable from './ConfigurationVersionsTable';
import { deepMerge } from '../../utils/configUtils';
import syncBdaIdpMutation from '../../graphql/queries/syncBdaIdp';

const client = generateClient();
const logger = new ConsoleLogger('ConfigurationLayout');

// Utility function to check if two values are numerically equivalent
const areNumericValuesEqual = (val1, val2) => {
  if (typeof val1 === 'number' && typeof val2 === 'number') {
    return val1 === val2;
  }
  const num1 = typeof val1 === 'number' ? val1 : parseFloat(val1);
  const num2 = typeof val2 === 'number' ? val2 : parseFloat(val2);
  if (!Number.isNaN(num1) && !Number.isNaN(num2)) {
    return num1 === num2;
  }
  return false;
};

const isNumericValue = (val) => {
  if (typeof val === 'number') return true;
  if (typeof val === 'string' && val.trim() !== '') {
    return !Number.isNaN(parseFloat(val)) && isFinite(val);
  }
  return false;
};

const ConfigurationLayout = () => {
  const {
    versions,
    loading: versionsLoading,
    fetchVersion,
    saveAsNewVersion,
    setActiveVersion,
    updateVersion,
    deleteVersion,
  } = useConfigurationVersions();

  // Version selection state
  const [selectedVersion, setSelectedVersion] = useState(null);
  const [selectedVersionData, setSelectedVersionData] = useState(null);
  const [defaultVersionData, setDefaultVersionData] = useState(null); // v0 for comparison
  const [loadingVersion, setLoadingVersion] = useState(false);

  // Configuration editing state (from develop branch)
  const [formValues, setFormValues] = useState({});
  const [jsonContent, setJsonContent] = useState('');
  const [yamlContent, setYamlContent] = useState('');
  const [isSaving, setIsSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [saveError, setSaveError] = useState(null);
  const [importSuccess, setImportSuccess] = useState(false);
  const [validationErrors, setValidationErrors] = useState([]);
  const [viewMode, setViewMode] = useState('form');
  const [showResetModal, setShowResetModal] = useState(false);
  const [showSaveAsNewModal, setShowSaveAsNewModal] = useState(false);
  const [showExportModal, setShowExportModal] = useState(false);
  const [showActivateModal, setShowActivateModal] = useState(false);
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [exportFormat, setExportFormat] = useState('json');
  const [exportFileName, setExportFileName] = useState('configuration');
  const [importError, setImportError] = useState(null);
  const [extractionSchema, setExtractionSchema] = useState(null);
  const [newVersionDescription, setNewVersionDescription] = useState('');

  // Configuration Library state
  const [showImportSourceModal, setShowImportSourceModal] = useState(false);
  const [showLibraryBrowserModal, setShowLibraryBrowserModal] = useState(false);
  const [showReadmeModal, setShowReadmeModal] = useState(false);
  const [libraryConfigs, setLibraryConfigs] = useState([]);
  const [selectedLibraryConfig, setSelectedLibraryConfig] = useState(null);
  const [readmeContent, setReadmeContent] = useState('');
  const [libraryLoading, setLibraryLoading] = useState(false);

  const editorRef = useRef(null);
  const { listConfigurations, getFile } = useConfigurationLibrary();
  const { settings } = useSettingsContext();

  // Check if current version has unsaved changes
  const hasUnsavedChanges = useMemo(() => {
    if (!selectedVersionData || !formValues || Object.keys(formValues).length === 0) {
      return false;
    }
    return JSON.stringify(formValues) !== JSON.stringify(selectedVersionData.configuration);
  }, [formValues, selectedVersionData]);

  // Handle version selection
  const handleVersionSelect = async (versionId) => {
    try {
      setLoadingVersion(true);
      console.log('Loading version:', versionId);
      const versionData = await fetchVersion(versionId);
      console.log('Version data received:', versionData);

      if (versionData && versionData.configuration) {
        let config;
        if (typeof versionData.configuration === 'string') {
          try {
            config = JSON.parse(versionData.configuration);
          } catch (parseError) {
            console.error('Error parsing configuration JSON:', parseError);
            setSaveError('Invalid configuration data format');
            return;
          }
        } else {
          config = versionData.configuration;
        }

        console.log('Parsed config:', config);

        setSelectedVersion(versionId);
        // Get the version data with isActive status from the versions list
        const versionFromList = versions.find((v) => v.versionId === versionId);
        const versionDataWithStatus = { ...versionData, isActive: versionFromList?.isActive };
        setSelectedVersionData(versionDataWithStatus);
        setFormValues(config);

        // Reset any unsaved changes indicators when switching versions
        setSaveSuccess(false);
        setSaveError(null);

        // Load v0 for comparison if not already loaded and not selecting v0
        if (versionId !== 'v0' && !defaultVersionData) {
          try {
            const v0Data = await fetchVersion('v0');
            if (v0Data && v0Data.configuration) {
              let v0Config;
              if (typeof v0Data.configuration === 'string') {
                v0Config = JSON.parse(v0Data.configuration);
              } else {
                v0Config = v0Data.configuration;
              }
              setDefaultVersionData({ ...v0Data, configuration: v0Config });
            }
          } catch (error) {
            console.warn('Could not load v0 for comparison:', error);
          }
        }

        console.log('State set - selectedVersion:', versionId);
        console.log('State set - formValues:', config);

        if (config.classes) {
          setExtractionSchema(config.classes);
        }

        // Update editor content
        const jsonString = JSON.stringify(config, null, 2);
        setJsonContent(jsonString);

        try {
          const yamlString = yaml.dump(config);
          setYamlContent(yamlString);
        } catch (e) {
          console.error('Error converting to YAML:', e);
          setYamlContent('# Error converting to YAML');
        }
      } else {
        console.error('No configuration data in version response:', versionData);
        setSaveError('No configuration data found for this version');
      }
    } catch (err) {
      console.error('Error loading version:', err);
      setSaveError(`Failed to load version: ${err.message}`);
    } finally {
      setLoadingVersion(false);
    }
  };

  // Handle back to versions list (now just clears selection)
  const handleBackToVersions = () => {
    setSelectedVersion(null);
    setSelectedVersionData(null);
    setFormValues({});
    setJsonContent('');
    setYamlContent('');
    setSaveError(null);
    setSaveSuccess(false);
  };

  // Handle save current version
  const handleSave = async () => {
    setIsSaving(true);
    setSaveError(null);
    setSaveSuccess(false);

    try {
      await updateVersion(selectedVersion, formValues);
      setSaveSuccess(true);
    } catch (error) {
      console.error('Save error:', error);
      setSaveError(error.message || 'Failed to save configuration');
    } finally {
      setIsSaving(false);
    }
  };

  // Handle save as new version
  const handleSaveAsNew = async () => {
    setIsSaving(true);
    setSaveError(null);
    setSaveSuccess(false);

    try {
      await saveAsNewVersion(formValues, newVersionDescription || `New version based on ${selectedVersion}`);
      setSaveSuccess(true);
      setShowSaveAsNewModal(false);
      setNewVersionDescription('');
      // Refresh versions list
      // TODO: Refresh versions
    } catch (error) {
      console.error('Save as new error:', error);
      setSaveError(error.message || 'Failed to save as new version');
    } finally {
      setIsSaving(false);
    }
  };

  // Handle activate version
  const handleActivateVersion = async () => {
    setIsSaving(true);
    setSaveError(null);

    try {
      await setActiveVersion(selectedVersion);
      setSaveSuccess(true);
      setShowActivateModal(false);
      // Refresh versions list to update active status
      await loadVersions();
      // Update version data to reflect active status
      setSelectedVersionData((prev) => ({ ...prev, isActive: true }));
    } catch (error) {
      console.error('Activate error:', error);
      setSaveError(error.message || 'Failed to activate version');
    } finally {
      setIsSaving(false);
    }
  };

  // Handle delete version
  const handleDeleteVersion = async () => {
    setIsSaving(true);
    setSaveError(null);

    try {
      await deleteVersion(selectedVersion);
      setShowDeleteModal(false);
      handleBackToVersions(); // Go back to versions list
    } catch (error) {
      console.error('Delete error:', error);
      setSaveError(error.message || 'Failed to delete version');
    } finally {
      setIsSaving(false);
    }
  };

  // Handle reset to default
  // Handle field-level reset to default (for individual field restore buttons)
  const handleFieldResetToDefault = async (fieldPath) => {
    // Can't reset v0 fields
    if (selectedVersion === 'v0' || !defaultVersionData) {
      return;
    }

    try {
      // Get the default value from v0
      const defaultValue = getValueByPath(defaultVersionData.configuration, fieldPath);

      // Update only this field in formValues
      const updatedFormValues = { ...formValues };
      setValueByPath(updatedFormValues, fieldPath, defaultValue);

      // Save the updated configuration to the same version ID
      await updateVersion(selectedVersion, updatedFormValues);

      // Update UI state
      setFormValues(updatedFormValues);
      setJsonContent(JSON.stringify(updatedFormValues, null, 2));
      setYamlContent(yaml.dump(updatedFormValues));
    } catch (error) {
      console.error('Field reset error:', error);
      setSaveError(error.message || 'Failed to reset field to default');
    }
  };

  // Handle full reset to default (All) - resets entire configuration to v0
  const handleResetToDefault = async () => {
    setIsSaving(true);
    setSaveError(null);
    setSaveSuccess(false);

    try {
      // Can't reset v0 to itself
      if (selectedVersion === 'v0') {
        setSaveError('Cannot reset v0 (default) to itself');
        return;
      }

      // Need v0 data to reset to
      if (!defaultVersionData) {
        setSaveError('Default version (v0) not available for reset');
        return;
      }

      // Reset current version to match v0
      const v0Config = defaultVersionData.configuration;

      // Save the v0 configuration to the same version ID
      await updateVersion(selectedVersion, v0Config);

      // Update UI state
      setFormValues(v0Config);
      setJsonContent(JSON.stringify(v0Config, null, 2));
      setYamlContent(yaml.dump(v0Config));

      if (v0Config.classes) {
        setExtractionSchema(v0Config.classes);
      }

      setSaveSuccess(true);
      setShowResetModal(false);
    } catch (error) {
      console.error('Reset error:', error);
      setSaveError(error.message || 'Failed to reset to default');
    } finally {
      setIsSaving(false);
    }
  };

  // Helper function to set value by path
  const setValueByPath = (obj, path, value) => {
    const keys = path.split('.');
    const lastKey = keys.pop();
    const target = keys.reduce((current, key) => {
      if (!current[key]) current[key] = {};
      return current[key];
    }, obj);
    target[lastKey] = value;
  };

  // Helper function to get value by path (e.g., "ocr.backend" -> formValues.ocr.backend)
  const getValueByPath = (obj, path) => {
    return path.split('.').reduce((current, key) => {
      if (current && typeof current === 'object') {
        // Handle array indices like "classes[0].name"
        const arrayMatch = key.match(/^(.+)\[(\d+)\]$/);
        if (arrayMatch) {
          const [, arrayKey, index] = arrayMatch;
          return current[arrayKey] && current[arrayKey][parseInt(index)];
        }
        return current[key];
      }
      return undefined;
    }, obj);
  };

  // Check if a field is customized compared to v0 (default)
  const isCustomized = (path) => {
    // Only show customization for versions other than v0
    if (selectedVersion === 'v0' || !defaultVersionData) {
      return false;
    }

    // Get value from current version and v0
    const currentValue = getValueByPath(formValues, path);
    const defaultValue = getValueByPath(defaultVersionData.configuration, path);

    // Deep comparison
    return JSON.stringify(currentValue) !== JSON.stringify(defaultValue);
  };

  // Show versions table and selected version editor on same page
  return (
    <>
      <SpaceBetween size="l">
        {/* Versions Table */}
        <Container header={<Header variant="h2">Configuration Versions</Header>}>
          <ConfigurationVersionsTable versions={versions} loading={versionsLoading} onVersionSelect={handleVersionSelect} />
        </Container>

        {/* Loading state for selected version */}
        {loadingVersion && (
          <Container header={<Header variant="h2">Loading Configuration</Header>}>
            <Box textAlign="center" padding="l">
              <Spinner size="large" />
              <Box padding="s">Loading configuration version {selectedVersion}...</Box>
            </Box>
          </Container>
        )}

        {/* Configuration Editor for selected version */}
        {selectedVersion && !loadingVersion && (
          <Container
            header={
              <Header
                variant="h2"
                actions={
                  <SpaceBetween direction="horizontal" size="xs">
                    <SegmentedControl
                      selectedId={viewMode}
                      onChange={({ detail }) => setViewMode(detail.selectedId)}
                      options={[
                        { id: 'form', text: 'Form View' },
                        { id: 'json', text: 'JSON View' },
                        { id: 'yaml', text: 'YAML View' },
                      ]}
                    />
                    <Button onClick={() => setShowExportModal(true)}>Export</Button>
                    <Button onClick={() => setShowImportSourceModal(true)}>Import</Button>
                    <Button onClick={() => window.location.reload()}>Refresh</Button>
                    <Button onClick={() => setShowActivateModal(true)} disabled={!selectedVersion || selectedVersionData?.isActive}>
                      Activate
                    </Button>
                    <Button onClick={() => setShowResetModal(true)} disabled={selectedVersion === 'v0'}>
                      Restore default (All)
                    </Button>
                    <Button onClick={() => setShowSaveAsNewModal(true)}>Save as Version</Button>
                    <Button
                      onClick={() => setShowDeleteModal(true)}
                      disabled={!selectedVersion || selectedVersion === 'v0' || selectedVersionData?.isActive}
                    >
                      Delete Version
                    </Button>
                    <Button
                      variant={hasUnsavedChanges ? 'primary' : 'normal'}
                      onClick={handleSave}
                      loading={isSaving}
                      disabled={!hasUnsavedChanges || selectedVersion === 'v0'}
                    >
                      Save Changes
                    </Button>
                  </SpaceBetween>
                }
              >
                Configuration Version ({selectedVersion})
              </Header>
            }
          >
            <SpaceBetween size="l">
              {/* Success/Error alerts */}
              {saveSuccess && (
                <Alert type="success" dismissible onDismiss={() => setSaveSuccess(false)}>
                  Configuration saved successfully!
                </Alert>
              )}
              {saveError && (
                <Alert type="error" dismissible onDismiss={() => setSaveError(null)}>
                  {saveError}
                </Alert>
              )}

              {/* Configuration content based on view mode */}
              {viewMode === 'form' && (
                <ConfigBuilder
                  schema={{
                    ...JSON.parse(selectedVersionData?.schema || '{}'),
                    properties: Object.fromEntries(
                      Object.entries(JSON.parse(selectedVersionData?.schema || '{}')?.properties || {}).filter(
                        ([key]) => key !== 'classes',
                      ),
                    ),
                  }}
                  formValues={formValues}
                  onChange={setFormValues}
                  extractionSchema={extractionSchema}
                  isCustomized={isCustomized}
                  onResetToDefault={handleFieldResetToDefault}
                  onSchemaChange={(schemaData, isDirty) => {
                    setExtractionSchema(schemaData);
                    setHasUnsavedChanges(isDirty);
                  }}
                />
              )}

              {viewMode === 'json' && (
                <Editor
                  height="70vh"
                  defaultLanguage="json"
                  value={jsonContent}
                  onChange={(value) => {
                    setJsonContent(value);
                    try {
                      const parsed = JSON.parse(value);
                      setFormValues(parsed);
                      if (parsed.classes) {
                        setExtractionSchema(parsed.classes);
                      }
                      try {
                        const yamlString = yaml.dump(parsed);
                        setYamlContent(yamlString);
                      } catch (yamlError) {
                        console.error('Error converting to YAML:', yamlError);
                      }
                    } catch (e) {
                      console.warn('Invalid JSON in editor');
                    }
                  }}
                  options={{
                    minimap: { enabled: false },
                    formatOnPaste: true,
                    formatOnType: true,
                    automaticLayout: true,
                    scrollBeyondLastLine: false,
                    folding: true,
                    lineNumbers: 'on',
                    renderLineHighlight: 'all',
                    tabSize: 2,
                  }}
                />
              )}

              {viewMode === 'yaml' && (
                <Editor
                  height="70vh"
                  defaultLanguage="yaml"
                  value={yamlContent}
                  onChange={(value) => {
                    setYamlContent(value);
                    try {
                      const parsed = yaml.load(value);
                      if (parsed && typeof parsed === 'object') {
                        setFormValues(parsed);
                        if (parsed.classes) {
                          setExtractionSchema(parsed.classes);
                        }
                        const jsonString = JSON.stringify(parsed, null, 2);
                        setJsonContent(jsonString);
                      }
                    } catch (e) {
                      console.warn('Invalid YAML in editor');
                    }
                  }}
                  options={{
                    minimap: { enabled: false },
                    formatOnPaste: true,
                    formatOnType: true,
                    automaticLayout: true,
                    scrollBeyondLastLine: false,
                    folding: true,
                    lineNumbers: 'on',
                    renderLineHighlight: 'all',
                    tabSize: 2,
                  }}
                />
              )}
            </SpaceBetween>
          </Container>
        )}
      </SpaceBetween>

      {/* Save as New Version Modal */}
      <Modal
        visible={showSaveAsNewModal}
        onDismiss={() => setShowSaveAsNewModal(false)}
        header="Save as New Version"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={() => setShowSaveAsNewModal(false)}>
                Cancel
              </Button>
              <Button variant="primary" onClick={handleSaveAsNew} loading={isSaving}>
                Save as New Version
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        <FormField label="Description">
          <Input
            value={newVersionDescription}
            onChange={({ detail }) => setNewVersionDescription(detail.value)}
            placeholder={`New version based on ${selectedVersion}`}
          />
        </FormField>
      </Modal>

      {/* Activate Version Modal */}
      <Modal
        visible={showActivateModal}
        onDismiss={() => setShowActivateModal(false)}
        header="Activate Version"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={() => setShowActivateModal(false)}>
                Cancel
              </Button>
              <Button variant="primary" onClick={handleActivateVersion} loading={isSaving}>
                Activate
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        <Box variant="span">
          Are you sure you want to activate version {selectedVersion}? This will make it the active configuration for document processing.
        </Box>
      </Modal>

      {/* Delete Version Modal */}
      <Modal
        visible={showDeleteModal}
        onDismiss={() => setShowDeleteModal(false)}
        header="Delete Version"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={() => setShowDeleteModal(false)}>
                Cancel
              </Button>
              <Button variant="primary" onClick={handleDeleteVersion} loading={isSaving}>
                Delete
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        <Box variant="span">
          Are you sure you want to delete version <Box variant="strong">{selectedVersion}</Box>? This action cannot be undone.
        </Box>
      </Modal>

      {/* Reset to Default Modal */}
      <Modal
        visible={showResetModal}
        onDismiss={() => setShowResetModal(false)}
        header="Reset to Default"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={() => setShowResetModal(false)}>
                Cancel
              </Button>
              <Button variant="primary" onClick={handleResetToDefault} loading={isSaving}>
                Reset
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        <Box variant="span">
          Are you sure you want to reset version {selectedVersion} to default values? This will overwrite all current settings.
        </Box>
      </Modal>
    </>
  );
};

export default ConfigurationLayout;
