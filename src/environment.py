import json
from os import environ
from typing import Dict, Optional

import boto3
from dotenv import load_dotenv
from injector import inject, singleton

load_dotenv()


@singleton
class Environment:
    @inject
    def __init__(self) -> None:
        secret_arn = environ.get('SECRET_ARN')
        self.__secret_environment: Dict[str, str] = self.__import_from(secret_arn) if secret_arn else {}

    def get(self, name: str) -> Optional[str]:
        return self.__secret_environment.get(name, environ.get(name))

    @staticmethod
    def __import_from(secret_arn: str) -> Dict[str, str]:
        secret_string = boto3.client('secretsmanager').get_secret_value(SecretId=secret_arn)['SecretString']
        try:
            return json.loads(secret_string)
        except json.JSONDecodeError:
            return {}
