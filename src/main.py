from typing import Optional

from injector import inject, Injector

from src.environment import Environment


@inject
def main(environment: Environment) -> None:
    print(f'Hello {environment.get('NAME')}')


# pylint: disable=unused-argument
def lambda_handler(event: Optional[dict] = None, context: Optional[dict] = None) -> None:
    Injector().call_with_injection(main)


if __name__ == '__main__':
    lambda_handler()
