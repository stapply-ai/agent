"""
Webhook signature verification utilities.

This module provides functions to verify webhook signatures sent by the agent.
Use these functions in your webhook endpoint to ensure the request is legitimate.
"""

import hmac
import hashlib
import time
from typing import Optional


def verify_webhook_signature(
    payload: str,
    signature: str,
    secret: str,
    timestamp: Optional[str] = None,
    tolerance: int = 300,
) -> bool:
    """
    Verify webhook signature to ensure request authenticity.

    Args:
        payload: The raw request body as string
        signature: The signature from X-Webhook-Signature header (format: sha256=...)
        secret: The webhook secret key
        timestamp: The timestamp from X-Webhook-Timestamp header
        tolerance: Maximum age of request in seconds (default: 5 minutes)

    Returns:
        True if signature is valid, False otherwise
    """
    if not signature or not secret:
        return False

    # Check timestamp to prevent replay attacks
    if timestamp:
        try:
            request_time = int(timestamp)
            current_time = int(time.time())
            if current_time - request_time > tolerance:
                print(f"Webhook request too old: {current_time - request_time}s")
                return False
        except (ValueError, TypeError):
            print("Invalid timestamp format")
            return False

    # Extract signature from "sha256=..." format
    if not signature.startswith("sha256="):
        print("Invalid signature format")
        return False

    expected_signature = signature[7:]  # Remove "sha256=" prefix

    # Generate expected signature
    computed_signature = hmac.new(
        secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256
    ).hexdigest()

    # Use constant-time comparison to prevent timing attacks
    is_valid = hmac.compare_digest(expected_signature, computed_signature)

    if not is_valid:
        print("Signature verification failed")

    return is_valid


def verify_webhook_request(
    request_body: str,
    signature_header: str,
    timestamp_header: str,
    secret: str,
    tolerance: int = 300,
) -> bool:
    """
    Verify a complete webhook request.

    Args:
        request_body: The raw request body
        signature_header: The X-Webhook-Signature header value
        timestamp_header: The X-Webhook-Timestamp header value
        secret: The webhook secret key
        tolerance: Maximum age of request in seconds

    Returns:
        True if request is valid, False otherwise
    """
    return verify_webhook_signature(
        payload=request_body,
        signature=signature_header,
        secret=secret,
        timestamp=timestamp_header,
        tolerance=tolerance,
    )
