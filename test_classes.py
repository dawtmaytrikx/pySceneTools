import unittest
import yaml
from classes import ircMessageParser

class TestIRCMessageParser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open('irc.yaml', 'r') as file:
            cls.config = yaml.safe_load(file)

    def test_pre_regex(self):
        for server in self.config['servers']:
            for channel in server['channels']:
                if 'pre_regex' in channel:
                    parser = ircMessageParser(channel)
                    for message in channel.get('pre_examples', []):
                        with self.subTest(server=server['name'], channel=channel['name'], message=message):
                            regex = channel['pre_regex']
                            print(f"Testing pre_regex for server: {server['name']}, channel: {channel['name']}, message: {message}, regex: {regex}")
                            result = parser.preparse(message)
                            print(f"Result: {result}")
                            self.assertIsNotNone(result.get("section"))
                            self.assertIsNotNone(result.get("release"))

    def test_nuke_regex(self):
        for server in self.config['servers']:
            for channel in server['channels']:
                if 'nuke_regex' in channel:
                    parser = ircMessageParser(channel)
                    for message in channel.get('nuke_examples', []):
                        with self.subTest(server=server['name'], channel=channel['name'], message=message):
                            regex = channel['nuke_regex']
                            print(f"Testing nuke_regex for server: {server['name']}, channel: {channel['name']}, message: {message}, regex: {regex}")
                            result = parser.nukeparse(message)
                            print(f"Result: {result}")
                            self.assertIsNotNone(result.get("type"))
                            self.assertIsNotNone(result.get("release"))
                            self.assertIsNotNone(result.get("reason"))
                            self.assertIsNotNone(result.get("nukenet"))

    def test_info_regex(self):
        for server in self.config['servers']:
            for channel in server['channels']:
                if 'info_regex' in channel:
                    parser = ircMessageParser(channel)
                    for message in channel.get('info_examples', []):
                        with self.subTest(server=server['name'], channel=channel['name'], message=message):
                            regex = channel['info_regex']
                            print(f"Testing info_regex for server: {server['name']}, channel: {channel['name']}, message: {message}, regex: {regex}")
                            result = parser.infoparse(message)
                            print(f"Result: {result}")
                            self.assertIsNotNone(result.get("type"))
                            self.assertIsNotNone(result.get("release"))
                            self.assertTrue(result.get("files") or result.get("size") or result.get("genre"))

    def test_pre_examples_against_nuke_and_info_regex(self):
        for server in self.config['servers']:
            for channel in server['channels']:
                if 'pre_examples' in channel:
                    parser = ircMessageParser(channel)
                    for message in channel.get('pre_examples', []):
                        if 'nuke_regex' in channel:
                            with self.subTest(server=server['name'], channel=channel['name'], message=message, regex='nuke_regex'):
                                print(f"Testing pre example against nuke_regex for server: {server['name']}, channel: {channel['name']}, message: {message}")
                                result = parser.nukeparse(message)
                                print(f"Result: {result}")
                                self.assertIsNone(result)
                        if 'info_regex' in channel:
                            with self.subTest(server=server['name'], channel=channel['name'], message=message, regex='info_regex'):
                                print(f"Testing pre example against info_regex for server: {server['name']}, channel: {channel['name']}, message: {message}")
                                result = parser.infoparse(message)
                                print(f"Result: {result}")
                                self.assertIsNone(result)

    def test_nuke_examples_against_pre_and_info_regex(self):
        for server in self.config['servers']:
            for channel in server['channels']:
                if 'nuke_examples' in channel:
                    parser = ircMessageParser(channel)
                    for message in channel.get('nuke_examples', []):
                        if 'pre_regex' in channel:
                            with self.subTest(server=server['name'], channel=channel['name'], message=message, regex='pre_regex'):
                                print(f"Testing nuke example against pre_regex for server: {server['name']}, channel: {channel['name']}, message: {message}")
                                result = parser.preparse(message)
                                print(f"Result: {result}")
                                self.assertIsNone(result)
                        if 'info_regex' in channel:
                            with self.subTest(server=server['name'], channel=channel['name'], message=message, regex='info_regex'):
                                print(f"Testing nuke example against info_regex for server: {server['name']}, channel: {channel['name']}, message: {message}")
                                result = parser.infoparse(message)
                                print(f"Result: {result}")
                                self.assertIsNone(result)

    def test_info_examples_against_pre_and_nuke_regex(self):
        for server in self.config['servers']:
            for channel in server['channels']:
                if 'info_examples' in channel:
                    parser = ircMessageParser(channel)
                    for message in channel.get('info_examples', []):
                        if 'pre_regex' in channel:
                            with self.subTest(server=server['name'], channel=channel['name'], message=message, regex='pre_regex'):
                                print(f"Testing info example against pre_regex for server: {server['name']}, channel: {channel['name']}, message: {message}")
                                result = parser.preparse(message)
                                print(f"Result: {result}")
                                self.assertIsNone(result)
                        if 'nuke_regex' in channel:
                            with self.subTest(server=server['name'], channel=channel['name'], message=message, regex='nuke_regex'):
                                print(f"Testing info example against nuke_regex for server: {server['name']}, channel: {channel['name']}, message: {message}")
                                result = parser.nukeparse(message)
                                print(f"Result: {result}")
                                self.assertIsNone(result)

if __name__ == '__main__':
    unittest.main()