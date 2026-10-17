import asyncio
import json
import os
import threading
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

from jarvis import brain, github_mcp as gh, hands, security


class GitHubTests(unittest.TestCase):
    args = {'owner': 'github', 'repo': 'github-mcp-server', 'path': 'LICENSE'}

    def test_embedded_resource_is_read_instead_of_metadata(self):
        result = NS(isError=False, content=[NS(type='text', text='download metadata'),
                    NS(type='resource', resource=NS(text='MIT License'))])
        self.assertEqual(gh._normalize(result, self.args)['content'], 'MIT License')

    def test_truncation_is_explicit(self):
        result = NS(isError=False, content=[NS(type='resource', resource=NS(text='x' * 7000))])
        out = gh._normalize(result, self.args)
        self.assertTrue(out['truncated'])
        self.assertEqual(out['total_characters'], 7000)
        self.assertEqual(len(out['content']), gh.MAX_CHARS)

    def test_error_and_directory_text_are_preserved(self):
        out = gh._normalize(NS(isError=True, content=[NS(type='text', text='Not Found')]), self.args)
        self.assertTrue(out['is_error'])
        self.assertEqual(out['content'], 'Not Found')

    def test_rejects_urls_traversal_and_controls_before_authentication(self):
        with patch.object(gh, '_credential') as auth:
            for arguments in [dict(self.args, owner='https://github.com'),
                              dict(self.args, path='../.env'), dict(self.args, repo='a/b'),
                              dict(self.args, path='a\nb'), dict(self.args, path='C:\\x')]:
                with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                    gh.get_file_contents(**arguments)
            auth.assert_not_called()

    def test_root_and_branch_are_supported(self):
        self.assertEqual(gh._arguments('github', 'repo', '', 'feature/test')['ref'], 'feature/test')
        self.assertEqual(gh._arguments('github', 'repo', '/', '')['path'], '')

    def test_only_fixed_read_tool_and_endpoint_used_and_token_redacted(self):
        seen = {}
        async def connect(cfg, action):
            seen['cfg'] = cfg
            session = NS(call_tool=AsyncMock(return_value=NS(isError=False,
                content=[NS(type='text', text='MIT secret-fixture-token')])) )
            seen['session'] = session
            return await action(session)
        def run(coro, timeout):
            return asyncio.run(coro)
        with patch.object(gh, '_credential', return_value='secret-fixture-token'), \
             patch.object(gh.mcp, '_connect_and_run', side_effect=connect), \
             patch.object(gh.mcp, '_run_sync', side_effect=run):
            output = gh.get_file_contents(**self.args)
        self.assertNotIn('secret-fixture-token', json.dumps(output))
        self.assertEqual(seen['cfg'].url, gh.ENDPOINT)
        self.assertEqual(seen['cfg'].headers['X-MCP-Readonly'], 'true')
        self.assertEqual(seen['cfg'].headers['X-MCP-Tools'], 'get_file_contents')
        seen['session'].call_tool.assert_awaited_once_with('get_file_contents', self.args)

    def test_login_failure_does_not_echo_stderr_or_credentials(self):
        with patch.dict(os.environ, {'JARVIS_GITHUB_TOKEN': ''}), \
             patch.object(gh.shutil, 'which', return_value='gh.exe'), \
             patch.object(gh.subprocess, 'run', return_value=NS(returncode=1, stdout='', stderr='secret')):
            with self.assertRaisesRegex(RuntimeError, 'gh auth login') as error:
                gh._credential()
            self.assertNotIn('secret', str(error.exception))

    def test_sdk_failure_sanitized(self):
        def run(coro, timeout):
            coro.close()
            raise RuntimeError('Authorization: Bearer secret')
        with patch.object(gh, '_credential', return_value='secret'), \
             patch.object(gh.mcp, '_run_sync', side_effect=run):
            with self.assertRaises(RuntimeError) as error:
                gh.get_file_contents(**self.args)
            self.assertNotIn('secret', str(error.exception))

    def test_disabled_does_not_access_credentials(self):
        with patch.dict(os.environ, {'JARVIS_GITHUB_ENABLED': 'false'}), patch.object(gh, '_credential') as auth:
            with self.assertRaisesRegex(RuntimeError, 'desabilitada'):
                gh.get_file_contents(**self.args)
            auth.assert_not_called()

    def test_interrupted_turn_does_not_start_request(self):
        event = threading.Event(); event.set()
        with security.session_context(None, event), patch.object(gh, '_credential') as auth:
            with self.assertRaises(security.TurnCancelled):
                gh.get_file_contents(**self.args)
            auth.assert_not_called()

    def test_tool_registered_with_flat_required_parameters(self):
        declaration = next(d for t in brain.TOOL_DECLARATIONS for d in t.function_declarations
                           if d.name == 'github_get_file_contents')
        self.assertEqual(set(declaration.parameters.required), {'owner', 'repo', 'path'})
        self.assertEqual(hands.TOOL_RISK[declaration.name], security.SAFE)
        self.assertIn(declaration.name, hands.TOOL_HANDLERS)
