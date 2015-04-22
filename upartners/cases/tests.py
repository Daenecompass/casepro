from __future__ import absolute_import, unicode_literals

from datetime import datetime
from django.core.exceptions import PermissionDenied
from django.core.urlresolvers import reverse
from django.utils import timezone
from mock import patch, call
from temba.types import Message as TembaMessage
from upartners.orgs_ext import TaskType
from upartners.profiles import ROLE_ANALYST, ROLE_MANAGER
from upartners.test import UPartnersTest
from .models import Case, Label, Partner, ACTION_OPEN, ACTION_NOTE, ACTION_LABEL, ACTION_UNLABEL, ACTION_CLOSE, ACTION_REOPEN, ACTION_REASSIGN
from .tasks import label_new_org_messages


class CaseTest(UPartnersTest):
    def test_lifecyle(self):
        d0 = datetime(2014, 1, 2, 6, 0, tzinfo=timezone.utc)
        d1 = datetime(2014, 1, 2, 7, 0, tzinfo=timezone.utc)
        d2 = datetime(2014, 1, 2, 8, 0, tzinfo=timezone.utc)
        d3 = datetime(2014, 1, 2, 9, 0, tzinfo=timezone.utc)
        d4 = datetime(2014, 1, 2, 10, 0, tzinfo=timezone.utc)
        d5 = datetime(2014, 1, 2, 11, 0, tzinfo=timezone.utc)
        d6 = datetime(2014, 1, 2, 12, 0, tzinfo=timezone.utc)
        d7 = datetime(2014, 1, 2, 13, 0, tzinfo=timezone.utc)

        with patch.object(timezone, 'now', return_value=d1):
            # MOH opens new case
            msg = TembaMessage.create(id=123, contact='C-001', created_on=d0, text="Hello")
            case = Case.open(self.unicef, self.user1, [self.aids], self.moh, msg)

        self.assertEqual(case.org, self.unicef)
        self.assertEqual(set(case.labels.all()), {self.aids})
        self.assertEqual(case.assignee, self.moh)
        self.assertEqual(case.contact_uuid, 'C-001')
        self.assertEqual(case.message_id, 123)
        self.assertEqual(case.message_on, d0)
        self.assertEqual(case.summary, "Hello")
        self.assertEqual(case.opened_on, d1)
        self.assertIsNone(case.closed_on)

        actions = case.actions.all()
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].action, ACTION_OPEN)
        self.assertEqual(actions[0].created_by, self.user1)
        self.assertEqual(actions[0].created_on, d1)
        self.assertEqual(actions[0].assignee, self.moh)

        self.assertTrue(case.accessible_by(self.user1, update=False))  # user who opened it can view and update
        self.assertTrue(case.accessible_by(self.user1, update=True))
        self.assertTrue(case.accessible_by(self.user2, update=False))  # user from same org can also view and update
        self.assertTrue(case.accessible_by(self.user2, update=True))
        self.assertTrue(case.accessible_by(self.user3, update=False))  # user from different partner with label access
        self.assertFalse(case.accessible_by(self.user3, update=True))
        self.assertFalse(case.accessible_by(self.user4, update=False))  # user from different org
        self.assertFalse(case.accessible_by(self.user4, update=False))

        with patch.object(timezone, 'now', return_value=d2):
            # other user in MOH adds a note
            case.note(self.user2, "Interesting")

        actions = case.actions.all()
        self.assertEqual(len(actions), 2)
        self.assertEqual(actions[1].action, ACTION_NOTE)
        self.assertEqual(actions[1].created_by, self.user2)
        self.assertEqual(actions[1].created_on, d2)
        self.assertEqual(actions[1].note, "Interesting")

        # user from other partner org can't close case
        self.assertRaises(PermissionDenied, case.close, self.user3)

        with patch.object(timezone, 'now', return_value=d3):
            # first user closes the case
            case.close(self.user1)

        self.assertEqual(case.opened_on, d1)
        self.assertEqual(case.closed_on, d3)

        actions = case.actions.all()
        self.assertEqual(len(actions), 3)
        self.assertEqual(actions[2].action, ACTION_CLOSE)
        self.assertEqual(actions[2].created_by, self.user1)
        self.assertEqual(actions[2].created_on, d3)

        with patch.object(timezone, 'now', return_value=d4):
            # but second user re-opens it
            case.reopen(self.user2)

        self.assertEqual(case.opened_on, d1)  # unchanged
        self.assertIsNone(case.closed_on)

        actions = case.actions.all()
        self.assertEqual(len(actions), 4)
        self.assertEqual(actions[3].action, ACTION_REOPEN)
        self.assertEqual(actions[3].created_by, self.user2)
        self.assertEqual(actions[3].created_on, d4)

        with patch.object(timezone, 'now', return_value=d5):
            # and re-assigns it to different partner
            case.reassign(self.user2, self.who)

        self.assertEqual(case.assignee, self.who)

        actions = case.actions.all()
        self.assertEqual(len(actions), 5)
        self.assertEqual(actions[4].action, ACTION_REASSIGN)
        self.assertEqual(actions[4].created_by, self.user2)
        self.assertEqual(actions[4].created_on, d5)
        self.assertEqual(actions[4].assignee, self.who)

        with patch.object(timezone, 'now', return_value=d6):
            # user from that partner re-labels it
            case.update_labels(self.user3, [self.pregnancy])

        actions = case.actions.all()
        self.assertEqual(len(actions), 7)
        self.assertEqual(actions[5].action, ACTION_LABEL)
        self.assertEqual(actions[5].created_by, self.user3)
        self.assertEqual(actions[5].created_on, d6)
        self.assertEqual(actions[5].label, self.pregnancy)
        self.assertEqual(actions[6].action, ACTION_UNLABEL)
        self.assertEqual(actions[6].created_by, self.user3)
        self.assertEqual(actions[6].created_on, d6)
        self.assertEqual(actions[6].label, self.aids)

        with patch.object(timezone, 'now', return_value=d7):
            # user from that partner org closes it again
            case.close(self.user3)

        self.assertEqual(case.opened_on, d1)
        self.assertEqual(case.closed_on, d7)

        actions = case.actions.all()
        self.assertEqual(len(actions), 8)
        self.assertEqual(actions[7].action, ACTION_CLOSE)
        self.assertEqual(actions[7].created_by, self.user3)
        self.assertEqual(actions[7].created_on, d7)


class LabelTest(UPartnersTest):
    def test_create(self):
        ebola = Label.create(self.unicef, "Ebola", "Msgs about ebola", ['ebola', 'fever'], [self.moh, self.who])
        self.assertEqual(ebola.org, self.unicef)
        self.assertEqual(ebola.name, "Ebola")
        self.assertEqual(ebola.description, "Msgs about ebola")
        self.assertEqual(ebola.keywords, 'ebola,fever')
        self.assertEqual(ebola.get_keywords(), ['ebola', 'fever'])
        self.assertEqual(set(ebola.get_partners()), {self.moh, self.who})
        self.assertEqual(unicode(ebola), "Ebola")

    def test_get_all(self):
        self.assertEqual(set(Label.get_all(self.unicef)), {self.aids, self.pregnancy})
        self.assertEqual(set(Label.get_all(self.unicef, self.user1)), {self.aids, self.pregnancy})  # MOH user
        self.assertEqual(set(Label.get_all(self.unicef, self.user3)), {self.aids})  # WHO user

    @patch('dash.orgs.models.TembaClient.get_messages')
    @patch('dash.orgs.models.TembaClient.label_messages')
    def test_label_new_messages_task(self, mock_label_messages, mock_get_messages):
        mock_get_messages.return_value = [
            TembaMessage.create(id=101, text="What is aids?"),
            TembaMessage.create(id=102, text="Can I catch Hiv?"),
            TembaMessage.create(id=103, text="I think I'm pregnant"),
            TembaMessage.create(id=104, text="Php is amaze"),
        ]
        mock_label_messages.return_value = None

        label_new_org_messages(self.unicef)

        mock_label_messages.assert_has_calls([call(messages=[101, 102], label='AIDS'),
                                              call(messages=[103], label='Pregnancy')],
                                             any_order=True)

        result = self.unicef.get_task_result(TaskType.label_messages)
        self.assertEqual(result['counts']['messages'], 4)
        self.assertEqual(result['counts']['labels'], 3)


class LabelCRUDLTest(UPartnersTest):
    def test_create(self):
        url = reverse('cases.label_create')

        # log in as a non-administrator
        self.login(self.user1)

        response = self.url_get('unicef', url)
        self.assertLoginRedirect(response, 'unicef', url)

        # log in as an administrator
        self.login(self.admin)

        response = self.url_get('unicef', url)
        self.assertEqual(response.status_code, 200)

        # submit with no data
        response = self.url_post('unicef', url, dict())
        self.assertEqual(response.status_code, 200)
        self.assertFormError(response, 'form', 'name', 'This field is required.')
        self.assertFormError(response, 'form', 'description', 'This field is required.')

        # submit again with data
        response = self.url_post('unicef', url, dict(name="Ebola", description="Msgs about ebola",
                                                     keywords="ebola,fever", partners=[self.moh.pk, self.who.pk]))
        self.assertEqual(response.status_code, 302)

        ebola = Label.objects.get(name="Ebola")
        self.assertEqual(ebola.org, self.unicef)
        self.assertEqual(ebola.name, "Ebola")
        self.assertEqual(ebola.description, "Msgs about ebola")
        self.assertEqual(ebola.keywords, 'ebola,fever')
        self.assertEqual(ebola.get_keywords(), ['ebola', 'fever'])
        self.assertEqual(set(ebola.get_partners()), {self.moh, self.who})

    def test_list(self):
        url = reverse('cases.label_list')

        # log in as an administrator
        self.login(self.admin)

        response = self.url_get('unicef', url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context['object_list']), [self.aids, self.pregnancy])


class PartnerTest(UPartnersTest):
    def test_create(self):
        wfp = Partner.create(self.unicef, "WFP")
        self.assertEqual(wfp.org, self.unicef)
        self.assertEqual(wfp.name, "WFP")
        self.assertEqual(unicode(wfp), "WFP")

        # create some users for this partner
        jim = self.create_user(self.unicef, wfp, ROLE_MANAGER, "Jim", "jim@wfp.org")
        kim = self.create_user(self.unicef, wfp, ROLE_ANALYST, "Kim", "kim@wfp.org")

        self.assertEqual(set(wfp.get_users()), {jim, kim})
        self.assertEqual(set(wfp.get_managers()), {jim})
        self.assertEqual(set(wfp.get_analysts()), {kim})

        # give this partner access to the AIDS and Code labels
        self.aids.partners.add(wfp)
        self.code.partners.add(wfp)

        self.assertEqual(set(wfp.get_labels()), {self.aids, self.code})
