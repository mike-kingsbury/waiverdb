# SPDX-License-Identifier: GPL-2.0+

import logging
import re
from fnmatch import fnmatch
from typing import Any

from werkzeug.exceptions import (
    BadGateway,
    InternalServerError,
    Unauthorized,
)

log = logging.getLogger(__name__)


def get_group_membership(ldap, user, con, ldap_search):
    try:
        results = con.search_s(
            ldap_search['BASE'], ldap.SCOPE_SUBTREE,
            ldap_search.get('SEARCH_STRING', '(memberUid={user})').format(user=user), ['cn']
        )
        return [group[1]['cn'][0].decode('utf-8') for group in results]
    except KeyError:
        log.exception('LDAP_SEARCHES parameter should contain the BASE key')
        raise InternalServerError('LDAP_SEARCHES parameter should contain the BASE key')
    except ldap.SERVER_DOWN:
        log.exception('The LDAP server is not reachable.')
        raise BadGateway('The LDAP server is not reachable.')
    except ldap.LDAPError:
        log.exception('Some error occurred initializing the LDAP connection.')
        raise Unauthorized('Some error occurred initializing the LDAP connection.')


def match_testcase_permissions(testcase: str, permissions: list[dict[str, Any]]):
    for permission in permissions:
        if "testcases" in permission:
            testcase_match = any(
                fnmatch(testcase, testcase_pattern)
                for testcase_pattern in permission["testcases"]
            )
        elif "_testcase_regex_pattern" in permission:
            testcase_match = re.search(
                permission["_testcase_regex_pattern"], testcase)
        else:
            continue

        if testcase_match:
            yield permission


def verify_authorization(user, testcase, permissions, ldap_host, ldap_searches):
    if not (ldap_host and ldap_searches):
        raise InternalServerError(('LDAP_HOST and LDAP_SEARCHES also need to be defined '
                                   'if PERMISSIONS is defined.'))

    allowed_groups = []
    for permission in match_testcase_permissions(testcase, permissions):
        if user in permission.get('users', []):
            return True
        allowed_groups += permission.get('groups', [])

    try:
        import ldap
    except ImportError:
        raise InternalServerError(('If PERMISSIONS is defined, '
                                   'python-ldap needs to be installed.'))

    try:
        con = ldap.initialize(ldap_host)
    except ldap.LDAPError:
        log.exception('Some error occurred initializing the LDAP connection.')
        raise Unauthorized('Some error occurred initializing the LDAP connection.')
    group_membership = set()

    for cur_ldap_search in ldap_searches:
        group_membership.update(
            get_group_membership(ldap, user, con, cur_ldap_search)
        )
        if group_membership & set(allowed_groups):
            return True

    if not group_membership:
        raise Unauthorized(f'Couldn\'t find user {user} in LDAP')

    raise Unauthorized(
        description=f'You are not authorized to submit a waiver for the test case {testcase}'
    )
