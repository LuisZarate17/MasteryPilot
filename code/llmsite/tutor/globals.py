loaded_model = None
loaded_tokenizer = None

def GetModelAndTokenizer():
    if loaded_model and loaded_tokenizer:
        return loaded_model, loaded_tokenizer
    raise ValueError("Model not initialized")