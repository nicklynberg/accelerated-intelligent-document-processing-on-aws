// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import React from 'react';
import PropTypes from 'prop-types';
import { Table, Box, SpaceBetween, Badge, Link } from '@cloudscape-design/components';
import { useCollection } from '@cloudscape-design/collection-hooks';

const ConfigurationVersionsTable = ({ versions = [], loading = false, onVersionSelect }) => {
  // Log the versions data to console for debugging
  console.log('ConfigurationVersionsTable - versions data:', versions);
  console.log('ConfigurationVersionsTable - loading:', loading);

  const columnDefinitions = [
    {
      id: 'versionId',
      header: 'Version ID',
      cell: (item) => (
        <Link
          href="#"
          onFollow={(event) => {
            event.preventDefault();
            onVersionSelect?.(item.versionId);
          }}
        >
          {item.versionId}
        </Link>
      ),
      sortingField: 'versionId',
    },
    {
      id: 'isActive',
      header: 'Active',
      cell: (item) => (item.isActive ? <Badge color="green">Active</Badge> : null),
      width: 100,
    },
    {
      id: 'createdAt',
      header: 'Created',
      cell: (item) => (item.createdAt ? new Date(item.createdAt).toLocaleString() : '-'),
      sortingField: 'createdAt',
    },
    {
      id: 'updatedAt',
      header: 'Updated',
      cell: (item) => (item.updatedAt ? new Date(item.updatedAt).toLocaleString() : '-'),
      sortingField: 'updatedAt',
    },
    {
      id: 'description',
      header: 'Description',
      cell: (item) => item.description || '-',
    },
  ];

  const { items, collectionProps } = useCollection(versions, {
    pagination: { pageSize: 10 },
    sorting: {
      defaultState: {
        sortingColumn: columnDefinitions[0],
        isDescending: true,
      },
    },
  });

  return (
    <Table
      {...collectionProps}
      columnDefinitions={columnDefinitions}
      items={items}
      loading={loading}
      loadingText="Loading versions..."
      empty={
        <Box margin={{ vertical: 'xs' }} textAlign="center" color="inherit">
          <SpaceBetween size="m">
            <b>No versions</b>
            <Box variant="p" color="inherit">
              No configuration versions found.
            </Box>
          </SpaceBetween>
        </Box>
      }
      header={<Box variant="h2">Configuration Versions ({versions.length})</Box>}
    />
  );
};

ConfigurationVersionsTable.propTypes = {
  versions: PropTypes.arrayOf(
    PropTypes.shape({
      versionId: PropTypes.string.isRequired,
      isActive: PropTypes.bool,
      createdAt: PropTypes.string,
      updatedAt: PropTypes.string,
      description: PropTypes.string,
    }),
  ),
  loading: PropTypes.bool,
  onVersionSelect: PropTypes.func,
};

export default ConfigurationVersionsTable;
