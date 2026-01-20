// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import gql from 'graphql-tag';

export default gql`
  query GetConfigVersion($versionId: String!) {
    getConfigVersion(versionId: $versionId) {
      success
      Schema
      Configuration
      error {
        type
        message
        validationErrors {
          field
          message
          type
        }
      }
    }
  }
`;
