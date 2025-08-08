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
S3_SIGNATURE_VERSION = os.environ.get('S3_SIGNATURE_VERSION', 's3')  # 's3', 's3v4', or 's3v2'

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

def test_s3_signature_error():
    """
    Test to reproduce and diagnose the SignatureDoesNotMatch error
    """
    print("=" * 80)
    print("FLYTEKIT S3 SIGNATURE ERROR DIAGNOSTIC TEST")
    print("=" * 80)
    print(f"Test started at: {datetime.now()}")

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

    # Create S3 configuration using parameters
    s3_config = S3Config(
        signature_version=S3_SIGNATURE_VERSION,
        endpoint=S3_ENDPOINT,
        access_key_id=S3_ACCESS_KEY_ID,
        secret_access_key=S3_SECRET_ACCESS_KEY
    )
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
                if "SignatureDoesNotMatch" in str(e):
                    print("  >>> This is the SignatureDoesNotMatch error we're investigating!")
                    analyze_signature_error(e, s3_config)

            except FlyteDownloadDataException as e:
                print(f"✗ FlyteDownloadDataException caught:")
                print(f"  Error: {e}")
                print(f"  Original exception: {e.__cause__}")

            except Exception as e:
                print(f"✗ Unexpected error: {type(e).__name__}: {e}")
                traceback.print_exc()

            # Test 4: Try different signature versions
            print("\n" + "-" * 60)
            print("TEST 4: Testing different signature versions")
            print("-" * 60)

            for sig_ver in SIGNATURE_VERSIONS_TO_TEST:
                try:
                    print(f"\nTrying signature version: {sig_ver}")
                    test_config = S3Config(
                        signature_version=sig_ver,
                        endpoint=S3_ENDPOINT,
                        access_key_id=S3_ACCESS_KEY_ID,
                        secret_access_key=S3_SECRET_ACCESS_KEY
                    )
                    test_data_config = DataConfig(s3=test_config)
                    test_provider = FileAccessProvider(
                        local_sandbox_dir=tmp_dir,
                        raw_output_prefix=f'{test_bucket}/raw/',
                        data_config=test_data_config
                    )

                    test_fs = test_provider.get_filesystem_for_path(test_path)
                    print(f"  ✓ Filesystem created with {sig_ver}")

                    # Try a simple operation
                    test_remote_path = f'{test_path}/sig_test_{sig_ver}.txt'
                    test_provider.put_data(test_file, test_remote_path)
                    print(f"  ✓ Successfully uploaded with signature version {sig_ver}")

                except Exception as e:
                    print(f"  ✗ Failed with {sig_ver}: {type(e).__name__}: {e}")
                    if "SignatureDoesNotMatch" in str(e):
                        print(f"    >>> SignatureDoesNotMatch error with {sig_ver}")

        except Exception as e:
            print(f"\n✗ CRITICAL ERROR: {type(e).__name__}: {e}")
            traceback.print_exc()

    print("\n" + "=" * 80)
    print("TEST COMPLETED")
    print("=" * 80)

def analyze_signature_error(error, s3_config):
    """
    Analyze the SignatureDoesNotMatch error and provide diagnostic information
    """
    print("\n" + "!" * 60)
    print("SIGNATURE ERROR ANALYSIS")
    print("!" * 60)

    print("Common causes of SignatureDoesNotMatch errors:")
    print("1. Incorrect AWS Access Key ID or Secret Access Key")
    print("2. Wrong signature version (s3, s3v4, s3v2)")
    print("3. Clock skew between client and server")
    print("4. Incorrect endpoint URL")
    print("5. Special characters in credentials not properly encoded")
    print("6. Region mismatch (for AWS S3)")
    print("7. MinIO-specific authentication issues")

    print(f"\nCurrent configuration analysis:")
    print(f"  Endpoint: {s3_config.endpoint}")
    print(f"  - Using HTTPS: {'✓' if s3_config.endpoint.startswith('https') else '✗'}")
    print(f"  - Custom endpoint (MinIO): ✓")
    print(f"  Signature Version: {s3_config.signature_version}")
    print(f"  - Recommended for MinIO: s3v4")
    print(f"  Access Key Length: {len(s3_config.access_key_id)} characters")
    print(f"  Secret Key Length: {len(s3_config.secret_access_key)} characters")

    print(f"\nRecommended fixes to try:")
    print(f"1. Change signature_version from '{s3_config.signature_version}' to 's3v4'")
    print(f"2. Verify credentials are correct for MinIO server")
    print(f"3. Check if MinIO server requires specific authentication settings")
    print(f"4. Ensure system clock is synchronized")
    print(f"5. Try without TLS (http://) if certificate issues exist")

if __name__ == "__main__":
    test_s3_signature_error()
