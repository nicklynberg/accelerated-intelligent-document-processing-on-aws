// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { useState, useEffect } from 'react';
import { generateClient } from 'aws-amplify/api';
import { ConsoleLogger } from 'aws-amplify/utils';
import getConfigVersionsQuery from '../graphql/queries/getConfigVersions';
import getConfigVersionQuery from '../graphql/queries/getConfigVersion';
import updateConfigurationMutation from '../graphql/queries/updateConfiguration';
import setActiveVersionMutation from '../graphql/queries/setActiveVersion';
import saveAsNewVersionMutation from '../graphql/queries/saveAsNewVersion';
import deleteConfigVersionMutation from '../graphql/queries/deleteConfigVersion';

const client = generateClient();
const logger = new ConsoleLogger('useConfigurationVersions');

const useConfigurationVersions = () => {
  const [versions, setVersions] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const fetchVersions = async () => {
    setLoading(true);
    setError(null);

    try {
      const result = await client.graphql({ query: getConfigVersionsQuery });
      const response = result.data.getConfigVersions;

      if (!response.success) {
        throw new Error(response.error?.message || 'Failed to fetch versions');
      }

      setVersions(response.versions || []);
    } catch (err) {
      logger.error('Error fetching configuration versions:', err);
      console.error('Full error object:', err);
      if (err.errors) {
        console.error('GraphQL errors:', err.errors);
        err.errors.forEach((gqlError, index) => {
          console.error(`Error ${index + 1}:`, gqlError.message);
        });
      }
      setError(err.message || 'Failed to fetch versions');
    } finally {
      setLoading(false);
    }
  };

  const fetchVersion = async (versionId) => {
    try {
      const result = await client.graphql({
        query: getConfigVersionQuery,
        variables: { versionId },
      });
      const response = result.data.getConfigVersion;

      if (!response.success) {
        throw new Error(response.error?.message || 'Failed to fetch version');
      }

      return {
        schema: response.Schema,
        configuration: response.Configuration,
      };
    } catch (err) {
      logger.error('Error fetching configuration version:', err);
      throw err;
    }
  };

  const updateVersion = async (versionId, configuration) => {
    try {
      const result = await client.graphql({
        query: updateConfigurationMutation,
        variables: {
          versionId,
          customConfig: JSON.stringify(configuration),
        },
      });
      const response = result.data.updateConfiguration;

      if (!response.success) {
        throw new Error(response.error?.message || 'Failed to update configuration');
      }

      return response;
    } catch (err) {
      logger.error('Error updating configuration version:', err);
      throw err;
    }
  };

  const setActiveVersion = async (versionId) => {
    try {
      const result = await client.graphql({
        query: setActiveVersionMutation,
        variables: { versionId },
      });
      const response = result.data.setActiveVersion;

      if (!response.success) {
        throw new Error(response.error?.message || 'Failed to set active version');
      }

      // Refresh versions list after setting active
      await fetchVersions();

      return response;
    } catch (err) {
      logger.error('Error setting active version:', err);
      throw err;
    }
  };

  const saveAsNewVersion = async (configuration, description, setAsActive = false) => {
    try {
      const result = await client.graphql({
        query: saveAsNewVersionMutation,
        variables: {
          configuration: JSON.stringify(configuration),
          description,
          setAsActive,
        },
      });
      const response = result.data.saveAsNewVersion;

      if (!response.success) {
        throw new Error(response.error?.message || 'Failed to save as new version');
      }

      // Refresh versions list after saving new version
      await fetchVersions();

      return response;
    } catch (err) {
      logger.error('Error saving as new version:', err);
      throw err;
    }
  };

  const deleteVersion = async (versionId) => {
    try {
      const result = await client.graphql({
        query: deleteConfigVersionMutation,
        variables: { versionId },
      });
      const response = result.data.deleteConfigVersion;

      if (!response.success) {
        throw new Error(response.error?.message || 'Failed to delete version');
      }

      // Refresh versions list after deleting
      await fetchVersions();

      return response;
    } catch (err) {
      logger.error('Error deleting version:', err);
      throw err;
    }
  };

  useEffect(() => {
    fetchVersions();
  }, []);

  return {
    versions,
    loading,
    error,
    fetchVersions,
    fetchVersion,
    updateVersion,
    setActiveVersion,
    saveAsNewVersion,
    deleteVersion,
  };
};

export default useConfigurationVersions;
