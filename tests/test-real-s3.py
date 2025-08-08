import logging
import sys
import os
import tempfile
import traceback
from datetime import datetime

# Add the project root to Python path to ensure we import the main flytekit module
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flytekit.loggers import logger
from flytekit.configuration import S3Config, DataConfig
from flytekit.core.data_persistence import FileAccessProvider
from flytekit.exceptions.system import FlyteUploadDataException, FlyteDownloadDataException

# ============================================================================
# TEST CONFIGURATION PARAMETERS
# ============================================================================
"""
This test can be configured using environment variables or by modifying the
defaults below.

USAGE EXAMPLES:

1. Run with default settings:
   python tests/test-real-s3.py

2. Run with custom endpoint:
   S3_ENDPOINT=http://localhost:9000 python tests/test-real-s3.py

3. Run with different signature version:
   S3_SIGNATURE_VERSION=s3v4 python tests/test-real-s3.py

4. Run with custom credentials:
   S3_ACCESS_KEY_ID=myuser S3_SECRET_ACCESS_KEY=mypass python tests/test-real-s3.py

5. Run with custom bucket:
   TEST_BUCKET=s3://my-test-bucket python tests/test-real-s3.py

6. Run with custom CA bundle:
   AWS_CA_BUNDLE=/path/to/ca-bundle.crt python tests/test-real-s3.py

ENVIRONMENT VARIABLES:
- S3_ENDPOINT: MinIO/S3 endpoint URL
- S3_ACCESS_KEY_ID: Access key for authentication
- S3_SECRET_ACCESS_KEY: Secret key for authentication
- S3_SIGNATURE_VERSION: Signature version ('s3', 's3v4', 's3v2')
- TEST_BUCKET: S3 bucket to use for testing
- TEST_PATH_PREFIX: Path prefix for test objects
- AWS_CA_BUNDLE: Path to SSL CA certificate bundle
"""

# S3/MinIO Connection Settings
S3_ENDPOINT = os.environ.get('S3_ENDPOINT', 'http://localhost:9000')
S3_ACCESS_KEY_ID = os.environ.get('S3_ACCESS_KEY_ID', 'minioadmin')
S3_SECRET_ACCESS_KEY = os.environ.get('S3_SECRET_ACCESS_KEY', 'minioadmin')
S3_SIGNATURE_VERSION = os.environ.get('S3_SIGNATURE_VERSION')  # 's3', 's3v4', or 's3v2'

# Test Bucket and Paths
TEST_BUCKET = os.environ.get('TEST_BUCKET', 's3://test-bucket')
TEST_PATH_PREFIX = os.environ.get('TEST_PATH_PREFIX', 'test-signature-error')

# SSL Certificate Settings
AWS_CA_BUNDLE = os.environ.get('AWS_CA_BUNDLE', '/path/to/ca-bundle.crt')

# Test Configuration
SIGNATURE_VERSIONS_TO_TEST = ['s3', 's3v4', 's3v2']  # All versions to test in diagnostic mode
LOG_LEVEL = logging.DEBUG

# ============================================================================
# LOGGING SETUP
# ============================================================================

logger.setLevel(LOG_LEVEL)
handler = logging.StreamHandler()
handler.setLevel(LOG_LEVEL)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

def enable_aws_debug_logging():
    """
    Enable verbose debug logging for AWS/BotoCore/S3FS/urllib3 to diagnose S3 issues
    like SignatureDoesNotMatch. WARNING: This can log sensitive headers.
    """
    # Attach handler to root so all libraries emit to console
    root_logger = logging.getLogger()
    if not any(isinstance(h, logging.StreamHandler) for h in root_logger.handlers):
        root_logger.addHandler(handler)
    root_logger.setLevel(LOG_LEVEL)

    # Verbose categories
    aws_loggers = [
        'botocore',
        'botocore.auth',
        'botocore.credentials',
        'botocore.endpoint',
        'botocore.parsers',
        'botocore.hooks',
        'botocore.utils',
        'aiobotocore',
        's3fs',
        'fsspec',
        'urllib3',
        'urllib3.connectionpool',
        'aiohttp.client',
    ]
    for name in aws_loggers:
        lg = logging.getLogger(name)
        lg.setLevel(logging.DEBUG)
        lg.propagate = True

    # Optional: wire-level HTTP logs (very noisy; may include auth headers)
    try:
        import http.client as http_client  # type: ignore
        http_client.HTTPConnection.debuglevel = 1
        logging.getLogger('http.client').setLevel(logging.DEBUG)
        logging.getLogger('http.client').propagate = True
    except Exception:
        pass

def test_s3_signature_error():
    """
    Test to reproduce and diagnose the SignatureDoesNotMatch error
    """
    print("=" * 80)
    print("FLYTEKIT S3 SIGNATURE ERROR DIAGNOSTIC TEST")
    print("=" * 80)
    print(f"Test started at: {datetime.now()}")

    print("\n🪵 Enabling AWS SDK debug logging (this can be very verbose)...")
    enable_aws_debug_logging()

    # Display current configuration
    print(f"\n📋 CONFIGURATION PARAMETERS:")
    print(f"  S3_ENDPOINT: {S3_ENDPOINT}")
    print(f"  S3_ACCESS_KEY_ID: {S3_ACCESS_KEY_ID}")
    print(f"  S3_SECRET_ACCESS_KEY: {'*' * len(S3_SECRET_ACCESS_KEY)}")
    print(f"  S3_SIGNATURE_VERSION: {S3_SIGNATURE_VERSION}")
    print(f"  TEST_BUCKET: {TEST_BUCKET}")
    print(f"  TEST_PATH_PREFIX: {TEST_PATH_PREFIX}")
    print(f"  AWS_CA_BUNDLE: {AWS_CA_BUNDLE}")

    # Check SSL certificate bundle
    print(f"\n🔒 SSL CERTIFICATE CHECK:")
    if AWS_CA_BUNDLE and os.path.exists(AWS_CA_BUNDLE):
        print(f"✓ SSL certificate bundle found at: {AWS_CA_BUNDLE}")
        # Set the environment variable if not already set
        if 'AWS_CA_BUNDLE' not in os.environ:
            os.environ['AWS_CA_BUNDLE'] = AWS_CA_BUNDLE
            print("  Environment variable AWS_CA_BUNDLE set automatically")
    else:
        print(f"✗ SSL certificate bundle not found - SSL errors may occur")
        print(f"  Expected location: {AWS_CA_BUNDLE}")

    # Create S3 configuration using parameters; omit signature_version if not set in env
    s3_kwargs = dict(
        endpoint=S3_ENDPOINT,
        access_key_id=S3_ACCESS_KEY_ID,
        secret_access_key=S3_SECRET_ACCESS_KEY,
    )
    if S3_SIGNATURE_VERSION:
        s3_kwargs["signature_version"] = S3_SIGNATURE_VERSION
    s3_config = S3Config(**s3_kwargs)
    data_config = DataConfig(s3=s3_config)

    print(f"\n🔧 S3 CONFIGURATION:")
    print(f"  Endpoint: {s3_config.endpoint}")
    print(f"  Signature Version: {s3_config.signature_version}")
    print(f"  Access Key ID: {s3_config.access_key_id}")
    print(f"  Secret Access Key: {'*' * len(s3_config.secret_access_key)}")

    test_bucket = TEST_BUCKET
    test_path = f'{test_bucket}/{TEST_PATH_PREFIX}'

    with tempfile.TemporaryDirectory() as tmp_dir:
        print(f"\nUsing temporary directory: {tmp_dir}")

        try:
            # Test 1: Create FileAccessProvider
            print("\n" + "-" * 60)
            print("TEST 1: Creating FileAccessProvider")
            print("-" * 60)

            provider = FileAccessProvider(
                local_sandbox_dir=tmp_dir,
                raw_output_prefix=f'{test_bucket}/raw/',
                data_config=data_config
            )
            print("✓ FileAccessProvider created successfully")

            # Test 2: Get filesystem
            print("\n" + "-" * 60)
            print("TEST 2: Getting S3 filesystem")
            print("-" * 60)

            fs = provider.get_filesystem_for_path(test_path)
            print("✓ S3 filesystem obtained successfully")
            print(f"  Filesystem type: {type(fs)}")

            # Test 3: Test basic S3 operations that might trigger the signature error
            print("\n" + "-" * 60)
            print("TEST 3: Testing S3 operations that trigger signature errors")
            print("-" * 60)

            # Create a test file locally
            test_file = os.path.join(tmp_dir, 'test_file.txt')
            with open(test_file, 'w') as f:
                f.write("This is a test file for S3 signature error reproduction\n")
                f.write(f"Created at: {datetime.now()}\n")

            print(f"Created local test file: {test_file}")

            # Test 3a: Try to put data (this often triggers SignatureDoesNotMatch)
            try:
                print("\nTesting put_data operation...")
                remote_path = f'{test_path}/put_test.txt'
                provider.put_data(test_file, remote_path)
                print(f"✓ Successfully uploaded file to: {remote_path}")

                # Test 3b: Try to get data back
                print("\nTesting get_data operation...")
                download_file = os.path.join(tmp_dir, 'downloaded_file.txt')
                provider.get_data(remote_path, download_file)
                print(f"✓ Successfully downloaded file to: {download_file}")

                # Verify content
                with open(download_file, 'r') as f:
                    content = f.read()
                    print(f"Downloaded content preview: {content[:100]}...")

            except FlyteUploadDataException as e:
                print(f"✗ FlyteUploadDataException caught:")
                print(f"  Error: {e}")
                print(f"  Original exception: {e.__cause__}")

            except FlyteDownloadDataException as e:
                print(f"✗ FlyteDownloadDataException caught:")
                print(f"  Error: {e}")
                print(f"  Original exception: {e.__cause__}")

            except Exception as e:
                print(f"✗ Unexpected error: {type(e).__name__}: {e}")
                traceback.print_exc()

        except Exception as e:
            print(f"\n✗ CRITICAL ERROR: {type(e).__name__}: {e}")
            traceback.print_exc()

    print("\n" + "=" * 80)
    print("TEST COMPLETED")
    print("=" * 80)

if __name__ == "__main__":
    test_s3_signature_error()
