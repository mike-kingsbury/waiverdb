# SPDX-License-Identifier: GPL-2.0+

import json
from base64 import b64encode

import mock
import ldap
import pytest


@pytest.mark.usefixtures('enable_permission_mapping')
@pytest.mark.usefixtures('enable_kerberos')
@mock.patch.multiple("gssapi.SecurityContext", complete=True,
                     __init__=mock.Mock(return_value=None),
                     step=mock.Mock(return_value=b"STOKEN"),
                     initiator_name="foo@EXAMPLE.ORG")
@mock.patch.multiple("gssapi.Credentials",
                     __init__=mock.Mock(return_value=None),
                     __new__=mock.Mock(return_value=None))
class TestAccessControl(object):

    data = {
        'subject_type': 'koji_build',
        'subject_identifier': 'glibc-2.26-27.fc27',
        'testcase': 'testcase1',
        'product_version': 'fool-1',
        'waived': True,
        'comment': 'it broke',
    }
    headers = {'Authorization':
               'Negotiate %s' % b64encode(b"CTOKEN").decode()}

    def test_ldap_host_base_not_defined(self, client, session):
        r = client.post('/api/v1.0/waivers/', data=json.dumps(self.data),
                        content_type='application/json', headers=self.headers)
        res_data = json.loads(r.get_data(as_text=True))
        assert r.status_code == 500
        assert res_data['message'] == ("LDAP_HOST and LDAP_BASE also need to be "
                                       "defined if PERMISSION_MAPPING is defined.")

    @pytest.mark.usefixtures('enable_ldap_host')
    def test_ldap_host_defined_base_not(self, client, session):
        self.test_ldap_host_base_not_defined(client, session)

    @pytest.mark.usefixtures('enable_ldap_base')
    def test_ldap_base_defined_host_not(self, client, session):
        self.test_ldap_host_base_not_defined(client, session)

    @pytest.mark.usefixtures('enable_ldap_host')
    @pytest.mark.usefixtures('enable_ldap_base')
    @mock.patch('ldap.initialize', side_effect=ldap.LDAPError())
    def test_initialization_ldap_connection(self, mocked, client, session):
        r = client.post('/api/v1.0/waivers/', data=json.dumps(self.data),
                        content_type='application/json', headers=self.headers)
        res_data = json.loads(r.get_data(as_text=True))
        assert r.status_code == 401
        assert res_data['message'] == "Some error occured initializing the LDAP connection."

    @pytest.mark.usefixtures('enable_ldap_host')
    @pytest.mark.usefixtures('enable_ldap_base')
    @mock.patch('waiverdb.api_v1.WaiversResource.get_group_membership', return_value=([]))
    def test_user_not_found_in_ldap(self, mocked_conn, client, session, monkeypatch):
        monkeypatch.setenv('KRB5_KTNAME', '/etc/foo.keytab')
        r = client.post('/api/v1.0/waivers/', data=json.dumps(self.data),
                        content_type='application/json', headers=self.headers)
        res_data = json.loads(r.get_data(as_text=True))
        assert r.status_code == 401
        assert res_data['message'] == "Couldn't find user foo in LDAP"

    @pytest.mark.usefixtures('enable_ldap_host')
    @pytest.mark.usefixtures('enable_ldap_base')
    @mock.patch('waiverdb.api_v1.WaiversResource.get_group_membership',
                return_value=(['factory-2-0', 'something-else']))
    def test_group_has_permission(self, mocked_conn, client, session, monkeypatch):
        monkeypatch.setenv('KRB5_KTNAME', '/etc/foo.keytab')
        r = client.post('/api/v1.0/waivers/', data=json.dumps(self.data),
                        content_type='application/json', headers=self.headers)
        res_data = json.loads(r.get_data(as_text=True))
        assert r.status_code == 201
        assert res_data['username'] == 'foo'
        assert res_data['subject'] == {'type': 'koji_build', 'item': 'glibc-2.26-27.fc27'}
        assert res_data['subject_type'] == 'koji_build'
        assert res_data['subject_identifier'] == 'glibc-2.26-27.fc27'
        assert res_data['testcase'] == 'testcase1'
        assert res_data['product_version'] == 'fool-1'
        assert res_data['waived'] is True
        assert res_data['comment'] == 'it broke'

    @pytest.mark.usefixtures('enable_ldap_host')
    @pytest.mark.usefixtures('enable_ldap_base')
    def test_user_has_permission(self, client, session, monkeypatch):
        monkeypatch.setenv('KRB5_KTNAME', '/etc/foo.keytab')
        self.data['testcase'] = 'testcase2'
        r = client.post('/api/v1.0/waivers/', data=json.dumps(self.data),
                        content_type='application/json', headers=self.headers)
        res_data = json.loads(r.get_data(as_text=True))
        assert r.status_code == 201
        assert res_data['username'] == 'foo'
        assert res_data['subject'] == {'type': 'koji_build', 'item': 'glibc-2.26-27.fc27'}
        assert res_data['subject_type'] == 'koji_build'
        assert res_data['subject_identifier'] == 'glibc-2.26-27.fc27'
        assert res_data['testcase'] == 'testcase2'
        assert res_data['product_version'] == 'fool-1'
        assert res_data['waived'] is True
        assert res_data['comment'] == 'it broke'

    @pytest.mark.usefixtures('enable_ldap_host')
    @pytest.mark.usefixtures('enable_ldap_base')
    @mock.patch('waiverdb.api_v1.WaiversResource.get_group_membership',
                return_value=(['factory-2-0', 'something-else']))
    def test_both_user_group_no_permission(self, mocked_conn, client, session, monkeypatch):
        monkeypatch.setenv('KRB5_KTNAME', '/etc/foo.keytab')
        self.data['testcase'] = 'testcase3'
        r = client.post('/api/v1.0/waivers/', data=json.dumps(self.data),
                        content_type='application/json', headers=self.headers)
        res_data = json.loads(r.get_data(as_text=True))
        assert r.status_code == 401
        assert res_data['message'] == ("You are not authorized to submit a waiver "
                                       "for the test case testcase3")
