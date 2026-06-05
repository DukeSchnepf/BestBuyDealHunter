#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# AWS cost audit — find out what's actually charging your card.
#
# Runs entirely with YOUR locally-configured AWS credentials (aws configure / an
# instance role). It is READ-ONLY: it only calls describe/list/get APIs. Nothing
# is created, modified, or deleted. No keys are printed.
#
# Usage:
#   aws configure         # one-time, if you haven't (or run on your EC2 instance)
#   bash deploy/aws_cost_audit.sh
#
# Needs these read permissions (admin users already have them):
#   ce:GetCostAndUsage, ec2:Describe*, elasticloadbalancing:Describe*,
#   rds:DescribeDBInstances
# ─────────────────────────────────────────────────────────────────────────────
set -uo pipefail   # NOT -e: we want to continue past per-service permission errors

if ! command -v aws >/dev/null 2>&1; then
  echo "ERROR: AWS CLI not found. Install it: https://aws.amazon.com/cli/"; exit 1
fi

echo "=============================================================="
echo " AWS COST AUDIT  ($(date -u '+%Y-%m-%d %H:%MZ'))"
echo "=============================================================="

echo; echo "## Account / identity"
aws sts get-caller-identity --output table 2>/dev/null || {
  echo "ERROR: credentials not configured or invalid. Run 'aws configure'."; exit 1; }

# ── This month's spend, broken down by service ───────────────────────────────
START=$(python3 -c "import datetime; print(datetime.date.today().replace(day=1))")
END=$(python3 -c "import datetime; print(datetime.date.today()+datetime.timedelta(days=1))")

echo; echo "## This month's cost by SERVICE ($START → today)"
aws ce get-cost-and-usage \
  --time-period Start="$START",End="$END" \
  --granularity MONTHLY --metrics UnblendedCost \
  --group-by Type=DIMENSION,Key=SERVICE \
  --query 'sort_by(ResultsByTime[0].Groups, &Metrics.UnblendedCost.Amount)[].[Keys[0],Metrics.UnblendedCost.Amount]' \
  --output table 2>/dev/null \
  || echo "  (Cost Explorer unavailable — enable it in the Billing console, or missing ce:GetCostAndUsage perm)"

echo; echo "## This month's cost by REGION"
aws ce get-cost-and-usage \
  --time-period Start="$START",End="$END" \
  --granularity MONTHLY --metrics UnblendedCost \
  --group-by Type=DIMENSION,Key=REGION \
  --query 'sort_by(ResultsByTime[0].Groups, &Metrics.UnblendedCost.Amount)[].[Keys[0],Metrics.UnblendedCost.Amount]' \
  --output table 2>/dev/null \
  || echo "  (skipped)"

# ── Resource sweep across ALL regions (the #1 hiding spot) ───────────────────
echo; echo "## Resource sweep across ALL regions"
echo "   (only regions with billable resources are shown)"
REGIONS=$(aws ec2 describe-regions --all-regions \
  --query 'Regions[?OptInStatus!=`not-opted-in`].RegionName' --output text 2>/dev/null)

if [[ -z "${REGIONS:-}" ]]; then
  echo "  Could not list regions (missing ec2:DescribeRegions?)."; REGIONS=""
fi

for r in $REGIONS; do
  findings=""

  inst=$(aws ec2 describe-instances --region "$r" \
    --query 'Reservations[].Instances[].[InstanceId,InstanceType,State.Name]' \
    --output text 2>/dev/null)
  [[ -n "$inst" ]] && findings+=$'\n  EC2 instances:\n'"$(echo "$inst" | sed 's/^/    /')"

  vols=$(aws ec2 describe-volumes --region "$r" \
    --filters Name=status,Values=available \
    --query 'Volumes[].[VolumeId,Size,VolumeType]' --output text 2>/dev/null)
  [[ -n "$vols" ]] && findings+=$'\n  ⚠ Unattached EBS volumes (billed!):\n'"$(echo "$vols" | sed 's/^/    /')"

  eips=$(aws ec2 describe-addresses --region "$r" \
    --query 'Addresses[?AssociationId==`null`].PublicIp' --output text 2>/dev/null)
  [[ -n "$eips" ]] && findings+=$'\n  ⚠ Unassociated Elastic IPs (billed!):\n    '"$eips"

  snaps=$(aws ec2 describe-snapshots --region "$r" --owner-ids self \
    --query 'length(Snapshots)' --output text 2>/dev/null)
  [[ -n "$snaps" && "$snaps" != "0" && "$snaps" != "None" ]] && findings+=$'\n  EBS snapshots: '"$snaps"

  nat=$(aws ec2 describe-nat-gateways --region "$r" \
    --filter Name=state,Values=available \
    --query 'NatGateways[].NatGatewayId' --output text 2>/dev/null)
  [[ -n "$nat" ]] && findings+=$'\n  ⚠ NAT Gateways (~$32/mo each):\n    '"$nat"

  albs=$(aws elbv2 describe-load-balancers --region "$r" \
    --query 'LoadBalancers[].LoadBalancerName' --output text 2>/dev/null)
  [[ -n "$albs" ]] && findings+=$'\n  ⚠ Load balancers (~$16+/mo each):\n    '"$albs"

  rds=$(aws rds describe-db-instances --region "$r" \
    --query 'DBInstances[].[DBInstanceIdentifier,DBInstanceClass]' --output text 2>/dev/null)
  [[ -n "$rds" ]] && findings+=$'\n  ⚠ RDS databases:\n'"$(echo "$rds" | sed 's/^/    /')"

  if [[ -n "$findings" ]]; then
    echo; echo "── $r ──$findings"
  fi
done

echo; echo "=============================================================="
echo " WHAT TO LOOK FOR"
echo "   • Resources in a region you don't normally use  ← most common surprise"
echo "   • ⚠ items above keep billing even with no running instance"
echo "   • 'EC2-Other' in the service list = usually EBS volumes / IPv4 / transfer"
echo "   • Public IPv4 is ~\$3.60/mo each (AWS bills all public IPv4 since 2024)"
echo " Set a budget alert: https://console.aws.amazon.com/billing/home#/budgets"
echo "=============================================================="
