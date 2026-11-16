# Court task failure emails

Deploy `template.json` in account `985454606291`, region `us-east-1`:

```sh
aws cloudformation deploy \
  --stack-name philly-courts-alerts \
  --template-file infrastructure/courts-alerts/template.json \
  --parameter-overrides AlertEmail=nicholas.adam.hand@gmail.com ClusterName=ujs-scraper \
  --region us-east-1
```

The deployment identity needs CloudFormation stack/change-set operations plus SNS topic/subscription/policy and EventBridge rule/target operations. No IAM roles or policies are created by this stack. The current `philly-gv` identity is denied CloudFormation CreateStack/DescribeStacks, SNS ListTopics, and EventBridge ListRules; the stack has **not** been installed.

Confirm the email subscription using AWS's confirmation email. Then check `SubscriptionsConfirmed` on the output topic ARN and publish an explicitly labeled test message before considering email delivery verified. Confirm the rule matches a `TaskFailedToStart` event and a nonzero worker/monitor exit, and excludes successful exits and unrelated task families. EventBridge retries delivery for up to 24 hours. The topic permits the EventBridge service to publish using AWS's documented SNS resource-policy pattern.

The payload contains only task ARN, time, stop code and reason. It contains no task environment, credentials, court inputs, or scrape results. ECS alerts are independent of GitHub and the ECS monitor. GitHub publication failures remain visible in the Courts publication workflow; a green submission is only acceptance of work.

The watchdog runs every ten minutes. A failed standalone watchdog triggers a separate recovery workflow from trusted main. It gets **one automatic attempt per run**, only for proven `CannotPullContainerError` startup failures. All workers and monitors must be stopped; exact coverage, conflict, queue and lease checks still apply. An ambiguous launch consumes the attempt and needs operator reconciliation. Reusable deployment health calls remain read-only and do not trigger the separate recovery workflow.
