// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import gql from 'graphql-tag';

export default gql`
  mutation SaveAsNewVersion($configuration: AWSJSON!, $versionName: String!, $description: String) {
    saveAsNewVersion(configuration: $configuration, versionName: $versionName, description: $description) {
      success
      message
      versionName
      error {
        type
        message
      }
    }
  }
`;
