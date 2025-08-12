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
from flytekit.utils.asyn import loop_manager

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

            # Create a test file with unique, verifiable content
            test_file = os.path.join(tmp_dir, 'test_file.txt')
            import uuid
            import hashlib

            # Generate unique test content
            test_uuid = str(uuid.uuid4())
            test_timestamp = datetime.now().isoformat()
            test_content = f"""FLYTEKIT S3 SIGNATURE TEST FILE
=================================
Test UUID: {test_uuid}
Created at: {test_timestamp}
S3 Endpoint: {S3_ENDPOINT}
S3 Signature Version: {S3_SIGNATURE_VERSION}
Test Bucket: {TEST_BUCKET}
Test Path Prefix: {TEST_PATH_PREFIX}

This file contains unique content to verify upload/download integrity.
If you can read this exact content after download, the S3 operations worked correctly!

Random data for uniqueness:
- Random number: {hash(test_uuid) % 1000000}
- Content length marker: [CONTENT_LENGTH_WILL_BE_INSERTED_HERE]
=================================
END OF TEST FILE"""

            # Calculate content length and insert it
            content_length = len(test_content.encode('utf-8'))
            test_content = test_content.replace('[CONTENT_LENGTH_WILL_BE_INSERTED_HERE]', f'{content_length} bytes')

            # Write the content and calculate hash for verification
            with open(test_file, 'w') as f:
                f.write(test_content)

            # Calculate SHA256 hash for integrity verification
            with open(test_file, 'rb') as f:
                file_hash = hashlib.sha256(f.read()).hexdigest()

            print(f"Created local test file: {test_file}")
            print(f"  File size: {len(test_content.encode('utf-8'))} bytes")
            print(f"  SHA256 hash: {file_hash}")
            print(f"  Test UUID: {test_uuid}")

            # Store these for later verification
            original_content = test_content
            original_hash = file_hash
            original_uuid = test_uuid

            # Test 3: Try original put operation
            print("\n" + "-" * 60)
            print("TEST 3: Testing Flytekit put operation")
            print("-" * 60)

            try:
                print("\nTesting put operation...")
                remote_path = f'{test_path}/put_test.txt'
                # Create a synchronous wrapper for the async _put method
                put_sync = loop_manager.synced(provider._put)
                put_sync(test_file, remote_path, recursive=False)
                print(f"✓ Successfully uploaded file to: {remote_path}")

                # Test 3b: Try to get data back
                print("\nTesting get_data operation...")
                download_file = os.path.join(tmp_dir, 'downloaded_file.txt')
                provider.get_data(remote_path, download_file)
                print(f"✓ Successfully downloaded file to: {download_file}")

                # Comprehensive content verification
                print("\n🔍 CONTENT VERIFICATION:")
                with open(download_file, 'r') as f:
                    downloaded_content = f.read()

                # Calculate hash of downloaded content
                with open(download_file, 'rb') as f:
                    downloaded_hash = hashlib.sha256(f.read()).hexdigest()

                # Verify content integrity
                content_match = downloaded_content == original_content
                hash_match = downloaded_hash == original_hash

                print(f"  Original file size: {len(original_content.encode('utf-8'))} bytes")
                print(f"  Downloaded file size: {len(downloaded_content.encode('utf-8'))} bytes")
                print(f"  Original SHA256: {original_hash}")
                print(f"  Downloaded SHA256: {downloaded_hash}")
                print(f"  Content match: {'✓ YES' if content_match else '✗ NO'}")
                print(f"  Hash match: {'✓ YES' if hash_match else '✗ NO'}")

                if content_match and hash_match:
                    print("  🎉 PERFECT MATCH! Upload/download integrity verified!")

                    # Extract and verify the UUID from downloaded content
                    import re
                    uuid_match = re.search(r'Test UUID: ([a-f0-9-]+)', downloaded_content)
                    if uuid_match and uuid_match.group(1) == original_uuid:
                        print(f"  ✓ UUID verification passed: {original_uuid}")
                    else:
                        print(f"  ✗ UUID verification failed!")
                else:
                    print("  ❌ CONTENT MISMATCH! There may be data corruption or encoding issues.")
                    if not content_match:
                        print("  Content differs between upload and download")
                    if not hash_match:
                        print("  Hash differs - possible data corruption")

                # Show a preview of the downloaded content
                print(f"\n📄 Downloaded content preview (first 200 chars):")
                print(f"  {downloaded_content[:200]}{'...' if len(downloaded_content) > 200 else ''}")

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
