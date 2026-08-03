import json
import tempfile
import unittest
from pathlib import Path

from backend.config.ai_config import AIConfigManager


class ImageConfigPersistenceTests(unittest.TestCase):
    def test_custom_image_connection_survives_manager_reload(self):
        """Image-only credentials must survive the same reload used at app startup."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir) / 'config'
            manager = AIConfigManager(str(config_dir))
            image = manager.image_config
            image.default_model = 'custom_openai'
            image.custom_openai_name = 'Local image gateway'
            image.custom_openai_api_key = 'test-image-key'
            image.custom_openai_base_url = 'http://127.0.0.1:8188/v1'
            image.custom_openai_model = 'image-model-test'

            self.assertTrue(manager.save_config())

            reloaded = AIConfigManager(str(config_dir)).image_config
            self.assertEqual('custom_openai', reloaded.default_model)
            self.assertEqual('Local image gateway', reloaded.custom_openai_name)
            self.assertEqual('test-image-key', reloaded.custom_openai_api_key)
            self.assertEqual('http://127.0.0.1:8188/v1', reloaded.custom_openai_base_url)
            self.assertEqual('image-model-test', reloaded.custom_openai_model)

            saved = json.loads((config_dir / 'ai_config.json').read_text(encoding='utf-8'))
            self.assertEqual('image-model-test', saved['image']['custom_openai_model'])


if __name__ == '__main__':
    unittest.main()
