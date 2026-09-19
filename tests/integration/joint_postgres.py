"""Recognize only the explicitly selected local joint acceptance database."""
import os


def is_joint_test_url(url):
    return (
        os.environ.get("CRM_JOINT_POSTGRES_ACCEPTANCE") == "1"
        and url.drivername == "postgresql+psycopg"
        and url.host == "127.0.0.1"
        and url.database == "joint_acceptance"
        and url.username == "joint_test"
        and url.port is not None
    )
