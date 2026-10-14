def connection_failure_message(error, host):
    """Classify errors without printing raw messages that may contain secrets."""
    message = str(error).lower()
    if 'password authentication failed' in message or getattr(error, 'pgcode', None) == '28P01':
        reason = 'Authentication failed. Check the database password and the exact username from Supabase Connect.'
    elif 'tenant or user not found' in message:
        reason = 'Pooler account was not found. Copy the session-pooler host and username from the same Supabase project.'
    elif any(term in message for term in ('network is unreachable', 'no route to host', 'cannot assign requested address')):
        reason = 'The database network address is unreachable from this computer.'
    elif any(term in message for term in ('could not translate host name', 'name or service not known', 'getaddrinfo failed')):
        reason = 'The database hostname could not be resolved. Check the hostname and network connectivity.'
    elif 'timeout' in message or 'timed out' in message:
        reason = 'The database connection timed out. Check network access, firewall rules and project availability.'
    elif 'ssl' in message or 'certificate' in message:
        reason = 'The secure connection failed. Check SSL mode and any required CA certificate.'
    else:
        reason = 'Check host, port, database, username, password, SSL mode and network access.'
    if host.endswith('.supabase.co') and host.startswith('db.'):
        reason += ' This is a Supabase direct endpoint, which normally requires IPv6. On an IPv4 network, select Connect > Session pooler and use its host and username instead.'
    return 'Database connection failed. ' + reason


