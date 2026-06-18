import unittest
import sys
from pathlib import Path

# Add runners to path so we can import semantic_hash
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "runners"))
import semantic_hash

class TestSemanticHash(unittest.TestCase):
    def test_python_ignores_comments_and_whitespace(self):
        code1 = "def a():\n    pass\n"
        code2 = "def a():\n    # This is a comment\n    pass\n\n\n"
        
        hash1 = semantic_hash.get_semantic_hash(code1, ".py")
        hash2 = semantic_hash.get_semantic_hash(code2, ".py")
        self.assertEqual(hash1, hash2, "AST hashing should ignore comments and newlines")

    def test_python_syntax_error_fallback(self):
        code1 = "def a(:"  # syntax error
        code2 = "def a(: " # syntax error with a space
        
        hash1 = semantic_hash.get_semantic_hash(code1, ".py")
        hash2 = semantic_hash.get_semantic_hash(code2, ".py")
        self.assertNotEqual(hash1, hash2, "Syntax error should fallback to raw hashing")
        
        import hashlib
        self.assertEqual(hash1, hashlib.sha256(code1.encode("utf-8")).hexdigest())

    def test_non_python_is_raw(self):
        text1 = "Some text"
        text2 = "Some text "
        
        hash1 = semantic_hash.get_semantic_hash(text1, ".txt")
        hash2 = semantic_hash.get_semantic_hash(text2, ".txt")
        self.assertNotEqual(hash1, hash2, "Text files should be hashed raw")
        
        import hashlib
        self.assertEqual(hash1, hashlib.sha256(text1.encode("utf-8")).hexdigest())

if __name__ == '__main__':
    unittest.main()
