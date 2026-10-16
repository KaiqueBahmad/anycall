from anycall import AnycallContext, supply

from .model.text_request import TextRequest
from .model.sentiment import Sentiment


class SentimentAnalyzer:
    """Analyzer for sentiment analysis operations."""

    @supply("analyze-sentiment")
    def analyze_sentiment(self, ctx: AnycallContext, req: TextRequest) -> Sentiment:
        """Analyze sentiment of text.

        Args:
            ctx: Invocation context
            req: Text request

        Returns:
            Sentiment analysis result
        """
        print(f"[python-supplier] analyze-sentiment received: {req.text!r}", flush=True)
        return Sentiment(text=req.text, label="positive")
