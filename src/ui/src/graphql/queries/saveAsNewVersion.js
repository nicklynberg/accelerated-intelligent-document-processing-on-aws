// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import gql from 'graphql-tag';

export default gql`
  mutation SaveAsNewVersion($configuration: AWSJSON!, $description: String, $setAsActive: Boolean) {
    saveAsNewVersion(configuration: $configuration, description: $description, setAsActive: $setAsActive) {
      success
      message
      error {
        type
        message
      }
    }
  }
`;
