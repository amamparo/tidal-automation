from os import getcwd

from aws_cdk import Stack, App, Duration
from aws_cdk.aws_ecr_assets import Platform
from aws_cdk.aws_events import Rule, Schedule
from aws_cdk.aws_events_targets import LambdaFunction
from aws_cdk.aws_lambda import DockerImageFunction, DockerImageCode, Architecture
from aws_cdk.aws_secretsmanager import Secret
from constructs import Construct


class TidalAutomation(Stack):
    def __init__(self, scope: Construct):
        super().__init__(scope, 'TidalAutomation')

        secret = Secret(self, 'Secret')

        daily_blend_function = DockerImageFunction(
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
                'MY_MOST_LISTENED_MIX_ID': '0109440f07375fd523d01076bfc28a',
                'DAILY_BLEND_PLAYLIST_ID': '00578a47-2b0b-49de-95a1-ec38696bfd73',
                'DAILY_BLEND_SIZE': '100',
            },
            timeout=Duration.minutes(15)
        )
        secret.grant_read(daily_blend_function)

        Rule(
            self,
            'UpdateDailyBlendSchedule',
            schedule=Schedule.cron(hour="11", minute="0", day="*", month="*", year="*"),
        ).add_target(LambdaFunction(daily_blend_function))

        kexp_function = DockerImageFunction(
            self,
            'UpdateKexpPlaylist',
            memory_size=512,
            code=DockerImageCode.from_image_asset(
                directory=getcwd(),
                platform=Platform.LINUX_ARM64,
                cmd=['src.update_kexp_playlist.lambda_handler']
            ),
            architecture=Architecture.ARM_64,
            environment={'SECRET_ARN': secret.secret_arn},
            timeout=Duration.minutes(15)
        )
        secret.grant_read(kexp_function)

        Rule(
            self,
            'UpdateKexpPlaylistSchedule',
            schedule=Schedule.cron(hour="11", minute="15", day="*", month="*", year="*"),
        ).add_target(LambdaFunction(kexp_function))


if __name__ == '__main__':
    app = App()
    TidalAutomation(app)
    app.synth()
