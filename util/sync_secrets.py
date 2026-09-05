import json
from typing import Dict

import boto3
from dotenv import dotenv_values

STACK_NAME = 'TidalAutomation'


def stack_outputs() -> Dict[str, str]:
    stack = boto3.client('cloudformation').describe_stacks(StackName=STACK_NAME)['Stacks'][0]
    return {output['OutputKey']: output['OutputValue'] for output in stack.get('Outputs', [])}


def current_secret(secrets, secret_arn: str) -> Dict[str, str]:
    stored = json.loads(secrets.get_secret_value(SecretId=secret_arn)['SecretString'])
    return stored if isinstance(stored, dict) else {}


def main() -> None:
    outputs = stack_outputs()
    provided_by_stack = set(filter(None, outputs.get('StackProvidedNames', '').split(',')))
    wanted = {name: value for name, value in dotenv_values().items()
              if value is not None and name not in provided_by_stack}

    secrets = boto3.client('secretsmanager')
    secret_arn = outputs['SecretArn']
    try:
        stored = current_secret(secrets, secret_arn)
    except (secrets.exceptions.ResourceNotFoundException, json.JSONDecodeError):
        stored = {}

    merged = {**stored, **wanted}
    if merged == stored:
        print(f'secret: already current, {len(stored)} names')
        return

    secrets.put_secret_value(SecretId=secret_arn, SecretString=json.dumps(merged))
    added = sorted(set(wanted) - set(stored))
    updated = sorted(name for name in wanted if name in stored and stored[name] != wanted[name])
    print(f'secret: {len(merged)} names ({added and "added " + ", ".join(added) or "added nothing"}; '
          f'{updated and "updated " + ", ".join(updated) or "updated nothing"})')

    orphaned = sorted(set(stored) - set(wanted))
    if orphaned:
        print(f'secret: kept but no longer in .env: {", ".join(orphaned)}')


if __name__ == '__main__':
    main()
