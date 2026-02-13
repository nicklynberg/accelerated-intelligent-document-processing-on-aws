// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import React from 'react';
import PropTypes from 'prop-types';
import { Table, Box, SpaceBetween, Badge, Header, ButtonDropdown } from '@cloudscape-design/components';

const ConfigurationComparison = ({ versions, configs }) => {
  // Safety checks
  if (!versions || !Array.isArray(versions) || !configs) {
    return (
      <Box textAlign="center" color="inherit">
        <SpaceBetween size="m">
          <b>Invalid comparison data</b>
          <Box variant="p">Unable to compare configurations due to missing data.</Box>
        </SpaceBetween>
      </Box>
    );
  }
  // Find differences between configurations - using backend logic
  const findDifferences = (configsToCompare) => {
    const differences = [];
    const ignoredFields = new Set(['UpdatedAt', 'Description', 'CreatedAt', 'IsActive', 'Configuration', 'version_name', 'classes']);

    // Get all nested paths from dictionary - backend style
    const getAllPaths = (dictionary, prefix = '') => {
      const paths = [];

      for (const [key, value] of Object.entries(dictionary || {})) {
        if (ignoredFields.has(key)) continue;

        const currentPath = prefix ? `${prefix}.${key}` : key;
        if (typeof value === 'object' && value !== null) {
          paths.push(...getAllPaths(value, currentPath));
        } else {
          paths.push(currentPath);
        }
      }
      return paths;
    };

    // Get nested value using dot notation path - backend style
    const getNestedValue = (dictionary, path) => {
      const keys = path.split('.');
      let current = dictionary;
      for (const key of keys) {
        if (typeof current === 'object' && current !== null && key in current) {
          current = current[key];
        } else {
          return null;
        }
      }
      return current;
    };

    // Get all possible paths from all configs
    const allPaths = new Set();
    Object.values(configsToCompare).forEach((config) => {
      // Now we receive merged config directly, not the old {custom, default, schema} format
      getAllPaths(config || {}).forEach((path) => allPaths.add(path));
    });

    // Sort paths for consistent ordering
    const sortedPaths = Array.from(allPaths).sort();

    // Check each path for differences
    sortedPaths.forEach((path) => {
      const values = {};
      let hasDifferences = false;
      let firstValue = null;
      let firstValueSet = false;

      versions.forEach((version) => {
        const config = configsToCompare[version];
        // Now we receive merged config directly, not the old {custom, default, schema} format
        const value = getNestedValue(config || {}, path);

        // Always include the value, even if null/undefined (missing field)
        const strValue =
          value === null || value === undefined ? '<missing>' : typeof value === 'string' ? value.trim() : String(value).trim();

        values[version] = strValue;

        // Check for differences using normalized values
        if (!firstValueSet) {
          firstValue = strValue;
          firstValueSet = true;
        } else if (firstValue !== strValue) {
          hasDifferences = true;
        }
      });

      // Include if there are differences (including missing vs present)
      if (hasDifferences) {
        differences.push({
          field: path,
          values,
        });
      }
    });

    return differences.sort((a, b) => a.field.localeCompare(b.field));
  };

  // Helper to get nested value from object using dot notation
  const getNestedValue = (obj, path) => {
    return path.split('.').reduce((current, key) => {
      return current && current[key] !== undefined ? current[key] : undefined;
    }, obj);
  };

  // Format value for display
  const formatValue = (value) => {
    if (value === '<missing>') return <Badge color="grey">Missing</Badge>;
    if (value === undefined) return <Badge color="grey">Not set</Badge>;
    if (value === null) return <Badge color="grey">null</Badge>;
    if (typeof value === 'boolean') return value ? 'true' : 'false';
    if (Array.isArray(value)) return `[${value.length} items]`;
    if (typeof value === 'object') return '[Object]';
    return String(value);
  };

  // Now configs are already merged, no need to parse old format
  const differences = findDifferences(configs);

  // Export functions
  const exportToCSV = () => {
    const headers = ['Field', ...versions];
    const rows = differences.map((diff) => [diff.field, ...versions.map((version) => diff.values[version] || 'Not set')]);

    const csvContent = [headers, ...rows].map((row) => row.map((cell) => `"${cell}"`).join(',')).join('\n');

    const blob = new Blob([csvContent], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `config-differences-${versions.join('-')}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const exportToJSON = () => {
    const exportData = {
      versions,
      differences: differences.map((diff) => ({
        field: diff.field,
        values: diff.values,
      })),
    };

    const jsonContent = JSON.stringify(exportData, null, 2);
    const blob = new Blob([jsonContent], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `config-differences-${versions.join('-')}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  // Debug logging
  console.log('Configs received:', configs);
  console.log('Differences found:', differences);

  // Create column definitions with equal width distribution
  const totalColumns = versions.length + 1; // +1 for field column
  const equalWidth = Math.floor(100 / totalColumns);

  const columnDefinitions = [
    {
      id: 'field',
      header: 'Field',
      cell: (item) => item.field,
      sortingField: 'field',
      width: `${equalWidth}%`,
    },
    ...versions.map((version) => ({
      id: version,
      header: version,
      cell: (item) => formatValue(item.values[version]),
      width: `${equalWidth}%`,
    })),
  ];

  return (
    <SpaceBetween size="m">
      {differences.length === 0 ? (
        <Box textAlign="center" color="inherit">
          <SpaceBetween size="m">
            <b>No differences found</b>
            <Box variant="p">The selected configuration versions are identical.</Box>
          </SpaceBetween>
        </Box>
      ) : (
        <Table
          resizableColumns
          wrapLines={true}
          columnDefinitions={columnDefinitions}
          items={differences}
          sortingDisabled={false}
          header={
            <Header
              actions={
                <ButtonDropdown
                  items={[
                    { text: 'Export as CSV', id: 'csv' },
                    { text: 'Export as JSON', id: 'json' },
                  ]}
                  onItemClick={({ detail }) => {
                    if (detail.id === 'csv') exportToCSV();
                    if (detail.id === 'json') exportToJSON();
                  }}
                >
                  Export
                </ButtonDropdown>
              }
            >
              Config differences between versions: [{versions.join(', ')}]
            </Header>
          }
          empty={
            <Box textAlign="center" color="inherit">
              No differences found
            </Box>
          }
        />
      )}
    </SpaceBetween>
  );
};

ConfigurationComparison.propTypes = {
  versions: PropTypes.arrayOf(PropTypes.string).isRequired,
  configs: PropTypes.object.isRequired,
};

export default ConfigurationComparison;
