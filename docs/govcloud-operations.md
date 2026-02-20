# GovCloud Operations

Monitoring, troubleshooting, and operational best practices for the GenAI IDP solution in GovCloud.

## Monitoring

### CloudWatch Dashboards

The solution deploys CloudWatch dashboards automatically. Access them via the CloudWatch console in your GovCloud region.

Key metrics to monitor:
- **Step Functions**: Execution success/failure rates, duration
- **Lambda Functions**: Invocation count, error rate, duration, throttles
- **SQS Queues**: Queue depth, age of oldest message
- **DynamoDB**: Read/write capacity, throttled requests

### CloudWatch Alarms

The stack creates alarms for critical failure conditions:
- Step Functions execution failures
- SQS dead-letter queue messages

Alarms publish to an SNS topic — subscribe your team's email or pager to receive notifications.

### Log Groups

All Lambda functions write to dedicated CloudWatch Log Groups with the naming convention `/aws/lambda/{stack-name}-{function-name}`. Use CloudWatch Logs Insights to query across functions:

```
fields @timestamp, @message
| filter @message like /ERROR/
| sort @timestamp desc
| limit 50
```

## Troubleshooting

### Document Processing Failures

1. **Check Step Functions execution history**: Open the Step Functions console, find the failed execution, and inspect the failed state's input/output
2. **Check Lambda logs**: The failed state maps to a specific Lambda — check its CloudWatch log group for the error
3. **Common causes**:
   - Textract unable to process document (unsupported format, corrupt file)
   - Bedrock model throttling (check for `ThrottlingException`)
   - S3 access denied (IAM or KMS key policy)

### VPC Connectivity Issues

If Lambda functions timeout after deploying in a VPC:
- Verify all required VPC endpoints exist (see [VPC Deployment Guide](./vpc-deployment.md))
- Check security group allows HTTPS outbound (port 443)
- Confirm subnets have routes to VPC endpoints
- Test DNS resolution: endpoint service names should resolve to private IPs

### Queue Backlog

If documents are queuing up and not processing:
- Check SQS queue depth in CloudWatch
- Verify Lambda concurrency limits aren't being hit
- Check the DynamoDB concurrency table for stuck entries
- Look for throttling errors in the QueueProcessor Lambda logs

## Operational Best Practices

- **Set up SNS subscriptions** for the alarm topic before processing production workloads
- **Enable S3 access logging** on the input and output buckets for audit trails
- **Review CloudWatch dashboards weekly** to catch trends before they become incidents
- **Test failover** by processing sample documents after any infrastructure changes
- **Monitor costs** through the AWS Billing console — GovCloud pricing differs from commercial regions

## Related Documentation

- [GovCloud Deployment Guide](./govcloud-deployment.md) — prerequisites, deployment packages, and deploy commands
- [GovCloud Architecture](./govcloud-architecture.md) — services removed vs. retained, limitations, and workarounds
- [Batch Jobs REST API](./govcloud-batch-api.md) — API reference, authentication, and bastion tunnel setup
- [VPC Deployment Guide](./vpc-deployment.md) — VPC endpoints, security groups, and network configuration
