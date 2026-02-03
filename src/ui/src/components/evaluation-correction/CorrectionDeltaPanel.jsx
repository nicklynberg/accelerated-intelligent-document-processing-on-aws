// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/* eslint-disable react/prop-types */
import React from 'react';
import { Box, Container, Header, SpaceBetween, Button, Table, StatusIndicator, Alert } from '@cloudscape-design/components';
import { ConsoleLogger } from 'aws-amplify/utils';

const logger = new ConsoleLogger('CorrectionDeltaPanel');

/**
 * Formats a value for display, truncating if too long
 */
const formatValue = (value, maxLength = 30) => {
  if (value === null || value === undefined) return '(empty)';
  const str = String(value);
  if (str.length > maxLength) {
    return `${str.substring(0, maxLength)}...`;
  }
  return str;
};

/**
 * CorrectionDeltaPanel - Shows pending corrections and provides save/export options
 */
const CorrectionDeltaPanel = ({
  corrections = [],
  onRemoveCorrection,
  onSaveBaselineCorrections,
  onSavePredictionCorrections,
  onExportPatches,
  isSaving = false,
  documentId = '',
  sectionId = '',
}) => {
  const baselineCorrections = corrections.filter((c) => c.source === 'baseline');
  const predictionCorrections = corrections.filter((c) => c.source === 'prediction');

  const handleExport = () => {
    const exportData = {
      documentId,
      sectionId,
      timestamp: new Date().toISOString(),
      corrections: corrections.map((c) => ({
        field: c.fieldName,
        path: c.path,
        pathString: c.pathString,
        source: c.source,
        originalValue: c.originalValue,
        correctedValue: c.newValue,
      })),
    };

    const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `correction-patches-${documentId.replace(/\//g, '_')}-${sectionId}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);

    if (onExportPatches) {
      onExportPatches(exportData);
    }
  };

  const columnDefinitions = [
    {
      id: 'source',
      header: 'Source',
      cell: (item) => (
        <StatusIndicator type={item.source === 'baseline' ? 'info' : 'pending'}>
          {item.source === 'baseline' ? 'Baseline' : 'Prediction'}
        </StatusIndicator>
      ),
      width: 100,
    },
    {
      id: 'field',
      header: 'Field',
      cell: (item) => <Box fontWeight="bold">{item.pathString}</Box>,
      width: 180,
    },
    {
      id: 'original',
      header: 'Original',
      cell: (item) => (
        <Box color="text-status-error">
          <s>{formatValue(item.originalValue)}</s>
        </Box>
      ),
      width: 150,
    },
    {
      id: 'corrected',
      header: 'Corrected',
      cell: (item) => (
        <Box color="text-status-success" fontWeight="bold">
          {formatValue(item.newValue)}
        </Box>
      ),
      width: 150,
    },
    {
      id: 'actions',
      header: 'Actions',
      cell: (item) => (
        <Button
          variant="icon"
          iconName="remove"
          onClick={() => onRemoveCorrection && onRemoveCorrection(item)}
          ariaLabel="Remove correction"
        />
      ),
      width: 80,
    },
  ];

  if (corrections.length === 0) {
    return (
      <Container header={<Header variant="h3">Pending Corrections</Header>}>
        <Box textAlign="center" color="text-body-secondary" padding="l">
          No corrections made yet. Edit values in the table above to create corrections.
        </Box>
      </Container>
    );
  }

  return (
    <Container
      header={
        <Header
          variant="h3"
          counter={`(${corrections.length})`}
          actions={
            <SpaceBetween direction="horizontal" size="xs">
              <Button iconName="download" onClick={handleExport} disabled={corrections.length === 0}>
                Export Patches
              </Button>
            </SpaceBetween>
          }
        >
          Pending Corrections
        </Header>
      }
    >
      <SpaceBetween size="m">
        <Table columnDefinitions={columnDefinitions} items={corrections} sortingDisabled variant="embedded" wrapLines />

        <Alert type="info">
          <strong>Save Options:</strong>
          <ul style={{ margin: '8px 0', paddingLeft: '20px' }}>
            <li>
              <strong>Save Baseline Corrections ({baselineCorrections.length}):</strong> Updates the evaluation baseline data
            </li>
            <li>
              <strong>Save Prediction Corrections ({predictionCorrections.length}):</strong> Updates the prediction output data
            </li>
            <li>
              <strong>Export Patches:</strong> Download corrections as JSON for bulk application
            </li>
          </ul>
        </Alert>

        <SpaceBetween direction="horizontal" size="xs">
          <Button
            variant="primary"
            onClick={onSaveBaselineCorrections}
            disabled={baselineCorrections.length === 0 || isSaving}
            loading={isSaving}
          >
            Save Baseline Corrections ({baselineCorrections.length})
          </Button>
          <Button
            variant="normal"
            onClick={onSavePredictionCorrections}
            disabled={predictionCorrections.length === 0 || isSaving}
            loading={isSaving}
          >
            Save Prediction Corrections ({predictionCorrections.length})
          </Button>
        </SpaceBetween>
      </SpaceBetween>
    </Container>
  );
};

export default CorrectionDeltaPanel;
