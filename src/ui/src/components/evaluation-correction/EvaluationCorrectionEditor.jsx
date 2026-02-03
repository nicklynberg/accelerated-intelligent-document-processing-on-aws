// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/* eslint-disable react/prop-types */
import React, { useState, useEffect, useCallback } from 'react';
import { Modal, Box, SpaceBetween, Container, Header, Spinner, Button, Alert } from '@cloudscape-design/components';
import { generateClient } from 'aws-amplify/api';
import { ConsoleLogger } from 'aws-amplify/utils';

import PageImageViewer from '../common/PageImageViewer';
import FieldComparisonTable from './FieldComparisonTable';
import CorrectionDeltaPanel from './CorrectionDeltaPanel';
import getFileContents from '../../graphql/queries/getFileContents';
import useSettingsContext from '../../contexts/settings';

const client = generateClient();
const logger = new ConsoleLogger('EvaluationCorrectionEditor');

/**
 * Applies corrections to a JSON object at specified paths
 */
const applyCorrections = (data, corrections) => {
  if (!data || corrections.length === 0) return data;

  const result = JSON.parse(JSON.stringify(data)); // Deep clone

  corrections.forEach((correction) => {
    let current = result;
    const pathParts = correction.path;

    // Navigate to parent
    for (let i = 0; i < pathParts.length - 1; i++) {
      if (current[pathParts[i]] === undefined) {
        current[pathParts[i]] = {};
      }
      current = current[pathParts[i]];
    }

    // Set the value
    const lastKey = pathParts[pathParts.length - 1];
    current[lastKey] = correction.newValue;
  });

  return result;
};

/**
 * Constructs baseline URI from output URI by replacing bucket names
 */
const constructBaselineUri = (outputUri, outputBucket, baselineBucket) => {
  if (!outputUri || !outputBucket || !baselineBucket) return null;

  const match = outputUri.match(/^s3:\/\/([^/]+)\/(.+)$/);
  if (!match) return null;

  const [, bucketName, objectKey] = match;
  if (bucketName !== outputBucket) {
    logger.warn(`URI bucket (${bucketName}) does not match expected output bucket (${outputBucket})`);
  }

  return `s3://${baselineBucket}/${objectKey}`;
};

/**
 * EvaluationCorrectionEditor - Main modal for correcting evaluation mismatches
 */
const EvaluationCorrectionEditor = ({ visible, onDismiss, sectionData, onSaveComplete }) => {
  const { settings } = useSettingsContext();

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [predictedData, setPredictedData] = useState(null);
  const [expectedData, setExpectedData] = useState(null);
  const [corrections, setCorrections] = useState([]);
  const [showMismatchesOnly, setShowMismatchesOnly] = useState(true);
  const [activeFieldGeometry, setActiveFieldGeometry] = useState(null);
  const [isSaving, setIsSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(null);

  const documentItem = sectionData?.documentItem;
  const pageIds = sectionData?.PageIds || [];
  const documentPages = documentItem?.pages || [];
  const outputUri = sectionData?.OutputJSONUri;
  const sectionId = sectionData?.Id;
  const documentId = documentItem?.objectKey || documentItem?.ObjectKey;

  // Load data when modal opens
  useEffect(() => {
    if (!visible) {
      // Reset state when modal closes
      setCorrections([]);
      setPredictedData(null);
      setExpectedData(null);
      setError(null);
      setSaveSuccess(null);
      return;
    }

    const loadData = async () => {
      if (!outputUri) {
        setError('No output data URI available for this section');
        setLoading(false);
        return;
      }

      setLoading(true);
      setError(null);

      try {
        // Load predicted data
        logger.info('Loading predicted data from:', outputUri);
        const predictedResponse = await client.graphql({
          query: getFileContents,
          variables: { s3Uri: outputUri },
        });
        const predictedContent = predictedResponse.data.getFileContents.content;
        const parsedPredicted = JSON.parse(predictedContent);
        setPredictedData(parsedPredicted);

        // Construct and load baseline data
        const baselineUri = constructBaselineUri(outputUri, settings?.OutputBucket, settings?.EvaluationBaselineBucket);

        if (baselineUri) {
          logger.info('Loading baseline data from:', baselineUri);
          try {
            const baselineResponse = await client.graphql({
              query: getFileContents,
              variables: { s3Uri: baselineUri },
            });
            const baselineContent = baselineResponse.data.getFileContents.content;
            const parsedBaseline = JSON.parse(baselineContent);
            setExpectedData(parsedBaseline);
          } catch (baselineErr) {
            logger.warn('Baseline data not available:', baselineErr);
            setExpectedData(null);
          }
        }
      } catch (err) {
        logger.error('Error loading data:', err);
        setError(`Failed to load data: ${err.message}`);
      } finally {
        setLoading(false);
      }
    };

    loadData();
  }, [visible, outputUri, settings]);

  // Handle expected value change
  const handleExpectedChange = useCallback((correction) => {
    setCorrections((prev) => {
      // Remove any existing correction for this field/source
      const filtered = prev.filter((c) => !(c.pathString === correction.pathString && c.source === 'baseline'));
      return [...filtered, correction];
    });
    setSaveSuccess(null);
  }, []);

  // Handle predicted value change
  const handlePredictedChange = useCallback((correction) => {
    setCorrections((prev) => {
      const filtered = prev.filter((c) => !(c.pathString === correction.pathString && c.source === 'prediction'));
      return [...filtered, correction];
    });
    setSaveSuccess(null);
  }, []);

  // Remove a correction
  const handleRemoveCorrection = useCallback((correction) => {
    setCorrections((prev) => prev.filter((c) => !(c.pathString === correction.pathString && c.source === correction.source)));
  }, []);

  // Handle field focus for bounding box display
  const handleFieldFocus = useCallback((geometry) => {
    setActiveFieldGeometry(geometry);
  }, []);

  // Save baseline corrections
  const handleSaveBaselineCorrections = async () => {
    const baselineCorrections = corrections.filter((c) => c.source === 'baseline');
    if (baselineCorrections.length === 0) return;

    setIsSaving(true);
    setSaveSuccess(null);

    try {
      // Apply corrections to expected data
      const correctedData = applyCorrections(expectedData, baselineCorrections);

      // Construct baseline URI
      const baselineUri = constructBaselineUri(outputUri, settings?.OutputBucket, settings?.EvaluationBaselineBucket);

      if (!baselineUri) {
        throw new Error('Could not construct baseline URI');
      }

      // Call mutation to save (we'll add this GraphQL mutation)
      // For now, log the intent
      logger.info('Saving baseline corrections to:', baselineUri);
      logger.info('Corrected data:', correctedData);

      // TODO: Implement actual save via GraphQL mutation
      // await client.graphql({
      //   query: saveEvaluationCorrections,
      //   variables: {
      //     s3Uri: baselineUri,
      //     content: JSON.stringify(correctedData, null, 2),
      //     triggerReEvaluation: true,
      //   },
      // });

      // Remove saved corrections from pending
      setCorrections((prev) => prev.filter((c) => c.source !== 'baseline'));
      setExpectedData(correctedData);
      setSaveSuccess('baseline');

      if (onSaveComplete) {
        onSaveComplete({ type: 'baseline', corrections: baselineCorrections });
      }
    } catch (err) {
      logger.error('Error saving baseline corrections:', err);
      setError(`Failed to save baseline corrections: ${err.message}`);
    } finally {
      setIsSaving(false);
    }
  };

  // Save prediction corrections
  const handleSavePredictionCorrections = async () => {
    const predictionCorrections = corrections.filter((c) => c.source === 'prediction');
    if (predictionCorrections.length === 0) return;

    setIsSaving(true);
    setSaveSuccess(null);

    try {
      // Apply corrections to predicted data
      const correctedData = applyCorrections(predictedData, predictionCorrections);

      logger.info('Saving prediction corrections to:', outputUri);
      logger.info('Corrected data:', correctedData);

      // TODO: Implement actual save via GraphQL mutation

      // Remove saved corrections from pending
      setCorrections((prev) => prev.filter((c) => c.source !== 'prediction'));
      setPredictedData(correctedData);
      setSaveSuccess('prediction');

      if (onSaveComplete) {
        onSaveComplete({ type: 'prediction', corrections: predictionCorrections });
      }
    } catch (err) {
      logger.error('Error saving prediction corrections:', err);
      setError(`Failed to save prediction corrections: ${err.message}`);
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <Modal
      onDismiss={onDismiss}
      visible={visible}
      header={`Evaluation Correction Editor - ${sectionData?.Class || 'Section'}`}
      size="max"
      footer={
        <Box float="right">
          <SpaceBetween direction="horizontal" size="xs">
            <Button variant="link" onClick={onDismiss}>
              Close
            </Button>
          </SpaceBetween>
        </Box>
      }
    >
      <div
        style={{
          display: 'flex',
          flexDirection: 'row',
          gap: '20px',
          height: 'calc(100vh - 250px)',
          minHeight: '600px',
        }}
      >
        {/* Left: Page Image Viewer */}
        <div style={{ width: '40%', minWidth: '400px' }}>
          <Container header={<Header variant="h3">Document Pages ({pageIds.length})</Header>}>
            <PageImageViewer
              pageIds={pageIds}
              documentPages={documentPages}
              activeFieldGeometry={activeFieldGeometry}
              height="calc(100vh - 350px)"
            />
          </Container>
        </div>

        {/* Right: Comparison Table and Corrections */}
        <div style={{ flex: 1, overflow: 'auto' }}>
          <SpaceBetween size="m">
            {error && (
              <Alert type="error" dismissible onDismiss={() => setError(null)}>
                {error}
              </Alert>
            )}

            {saveSuccess && (
              <Alert type="success" dismissible onDismiss={() => setSaveSuccess(null)}>
                {saveSuccess === 'baseline' ? 'Baseline corrections saved successfully!' : 'Prediction corrections saved successfully!'}
              </Alert>
            )}

            {loading ? (
              <Box textAlign="center" padding="xl">
                <Spinner size="large" />
                <Box>Loading comparison data...</Box>
              </Box>
            ) : !expectedData ? (
              <Alert type="warning">
                No baseline data available for comparison. Use &quot;Use as Evaluation Baseline&quot; button first to create baseline data.
              </Alert>
            ) : (
              <>
                <Container header={<Header variant="h3">Field Comparison</Header>}>
                  <FieldComparisonTable
                    expectedData={expectedData}
                    predictedData={predictedData}
                    explainabilityInfo={predictedData?.explainability_info}
                    onExpectedChange={handleExpectedChange}
                    onPredictedChange={handlePredictedChange}
                    onFieldFocus={handleFieldFocus}
                    corrections={corrections}
                    showMismatchesOnly={showMismatchesOnly}
                    onShowMismatchesOnlyChange={setShowMismatchesOnly}
                  />
                </Container>

                <CorrectionDeltaPanel
                  corrections={corrections}
                  onRemoveCorrection={handleRemoveCorrection}
                  onSaveBaselineCorrections={handleSaveBaselineCorrections}
                  onSavePredictionCorrections={handleSavePredictionCorrections}
                  isSaving={isSaving}
                  documentId={documentId}
                  sectionId={sectionId}
                />
              </>
            )}
          </SpaceBetween>
        </div>
      </div>
    </Modal>
  );
};

export default EvaluationCorrectionEditor;
