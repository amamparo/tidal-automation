from os import getcwd

from aws_cdk import Stack, App, Duration
from aws_cdk.aws_ecr_assets import Platform
from aws_cdk.aws_events import Rule, Schedule
from aws_cdk.aws_events_targets import LambdaFunction
from aws_cdk.aws_lambda import DockerImageFunction, DockerImageCode, Architecture
from aws_cdk.aws_secretsmanager import Secret
from constructs import Construct


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
            environment={
                'SECRET_ARN': secret.secret_arn,
                'NEW_ARRIVALS_MIX_ID': '011f771e2ce4e3f379afe2d4491217',
                'DAILY_DISCOVER_MIX_ID': '016daa0bd02387c1695c2cff1c8b30',
                'DAILY_BLEND_PLAYLIST_ID': '00578a47-2b0b-49de-95a1-ec38696bfd73',
                'DAILY_BLEND_SIZE': '100',
            },
            timeout=Duration.minutes(15)
        )
        secret.grant_read(update_daily_blend)

        Rule(
            self,
            'UpdateDailyBlendSchedule',
            schedule=Schedule.cron(hour='10', minute='00'),
            targets=[LambdaFunction(update_daily_blend)]
        )

        update_dub_techno = DockerImageFunction(
            self,
            'UpdateDubTechno',
            memory_size=256,
            code=DockerImageCode.from_image_asset(
                directory=getcwd(),
                platform=Platform.LINUX_ARM64,
                cmd=['src.update_dub_techno.lambda_handler']
            ),
            architecture=Architecture.ARM_64,
            environment={
                'SECRET_ARN': secret.secret_arn,
                'DUB_TECHNO_PLAYLIST_ID': '70bf74d2-2b2f-4470-8d0d-582a18fdd2bf',
                'DUB_TECHNO_SIZE': '100',
            },
            reserved_concurrent_executions=1,
            retry_attempts=0,
            timeout=Duration.minutes(15)
        )
        secret.grant_read(update_dub_techno)

        Rule(
            self,
            'UpdateDubTechnoSchedule',
            schedule=Schedule.cron(hour='10', minute='15'),
            targets=[LambdaFunction(update_dub_techno)]
        )

        update_berghain_sound = DockerImageFunction(
            self,
            'UpdateBerghainSound',
            memory_size=256,
            code=DockerImageCode.from_image_asset(
                directory=getcwd(),
                platform=Platform.LINUX_ARM64,
                cmd=['src.update_berghain_sound.lambda_handler']
            ),
            architecture=Architecture.ARM_64,
            environment={
                'SECRET_ARN': secret.secret_arn,
                'BERGHAIN_SOUND_PLAYLIST_ID': 'f3986534-6e3d-4a90-8c3a-1281260a1da2',
                'BERGHAIN_SOUND_SIZE': '100',
            },
            reserved_concurrent_executions=1,
            retry_attempts=0,
            timeout=Duration.minutes(15)
        )
        secret.grant_read(update_berghain_sound)

        Rule(
            self,
            'UpdateBerghainSoundSchedule',
            schedule=Schedule.cron(hour='10', minute='30'),
            targets=[LambdaFunction(update_berghain_sound)]
        )


if __name__ == '__main__':
    app = App()
    TidalAutomation(app)
    app.synth()
