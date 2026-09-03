from tidalapi import Session


def main() -> None:
    tidal_session = Session()
    tidal_session.login_oauth_simple()
    print(tidal_session.refresh_token)


if __name__ == '__main__':
    main()
