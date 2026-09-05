from os import getcwd

from aws_cdk import Stack, App, Duration, CfnOutput
from aws_cdk.aws_ecr_assets import Platform
from aws_cdk.aws_events import Rule, Schedule
from aws_cdk.aws_events_targets import LambdaFunction
from aws_cdk.aws_lambda import DockerImageFunction, DockerImageCode, Architecture
from aws_cdk.aws_secretsmanager import Secret
from constructs import Construct


DAILY_BLEND_ENVIRONMENT = {
    'NEW_ARRIVALS_MIX_ID': '011f771e2ce4e3f379afe2d4491217',
    'DAILY_DISCOVER_MIX_ID': '016daa0bd02387c1695c2cff1c8b30',
    'DAILY_BLEND_PLAYLIST_ID': '00578a47-2b0b-49de-95a1-ec38696bfd73',
    'DAILY_BLEND_SIZE': '100',
}

DARKROOM_ENVIRONMENT = {
    'DARKROOM_PLAYLIST_ID': '70bf74d2-2b2f-4470-8d0d-582a18fdd2bf',
    'DARKROOM_SIZE': '100',
}


class TidalAutomation(Stack):
    def __init__(self, scope: Construct) -> None:
        super().__init__(scope, 'TidalAutomation')

        secret = Secret(self, 'Secret')

        update_daily_blend = DockerImageFunction(
            self,
            'UpdateDailyBlend',
            memory_size=128,
            code=DockerImageCode.from_image_asset(
                directory=getcwd(),
                platform=Platform.LINUX_ARM64,
                cmd=['src.update_daily_blend.lambda_handler']
            ),
            architecture=Architecture.ARM_64,
            environment={'SECRET_ARN': secret.secret_arn, **DAILY_BLEND_ENVIRONMENT},
            timeout=Duration.minutes(15)
        )
        secret.grant_read(update_daily_blend)

        Rule(
            self,
            'UpdateDailyBlendSchedule',
            schedule=Schedule.cron(hour='10', minute='00'),
            targets=[LambdaFunction(update_daily_blend)]
        )

        update_darkroom = DockerImageFunction(
            self,
            'UpdateDarkroom',
            memory_size=256,
            code=DockerImageCode.from_image_asset(
                directory=getcwd(),
                platform=Platform.LINUX_ARM64,
                cmd=['src.update_darkroom.lambda_handler']
            ),
            architecture=Architecture.ARM_64,
            environment={'SECRET_ARN': secret.secret_arn, **DARKROOM_ENVIRONMENT},
            reserved_concurrent_executions=1,
            retry_attempts=0,
            timeout=Duration.minutes(15)
        )
        secret.grant_read(update_darkroom)

        Rule(
            self,
            'UpdateDarkroomSchedule',
            schedule=Schedule.cron(hour='10', minute='15'),
            targets=[LambdaFunction(update_darkroom)]
        )

        CfnOutput(self, 'SecretArn', value=secret.secret_arn)
        CfnOutput(self, 'StackProvidedNames',
                  value=','.join(sorted({*DAILY_BLEND_ENVIRONMENT, *DARKROOM_ENVIRONMENT})))


if __name__ == '__main__':
    app = App()
    TidalAutomation(app)
    app.synth()
