from anycall import supply

from .model.text_request import TextRequest
from .model.sentiment import Sentiment


class SentimentAnalyzer:
    """Analyzer for sentiment analysis operations."""

    @supply("analyze-sentiment")
    def analyze_sentiment(self, req: TextRequest) -> Sentiment:
        """Analyze sentiment of text.

        Args:
            req: Text request

        Returns:
            Sentiment analysis result
        """
        return Sentiment(text=req.text, label="positive")
