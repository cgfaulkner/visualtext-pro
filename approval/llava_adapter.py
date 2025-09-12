# approval/llava_adapter.py
class LegacyLLaVAAdapter:
    def __init__(self, new_generator):
        self.gen = new_generator
        
    def generate_alt_text(self, image_path=None, context=None, **kwargs):
        rec = {"image_path": image_path, "context": context}
        return self.gen.generate_alt(rec)