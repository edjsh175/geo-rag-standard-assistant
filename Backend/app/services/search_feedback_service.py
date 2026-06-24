"""Search feedback persistence."""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import text

from app.core.auth import UserIdentity
from app.core.database import db_manager
from app.models.search_models import FeedbackRequest, FeedbackResponse


class SearchFeedbackService:
    """Persist user feedback on search results."""

    async def submit_feedback(
        self,
        feedback: FeedbackRequest,
        current_user: UserIdentity,
    ) -> FeedbackResponse:
        if not db_manager.postgres_sessionmaker:
            raise RuntimeError("PostgreSQL connection is not initialized")

        feedback_id = str(uuid4())
        sql = text(
            """
            INSERT INTO search_feedback (
                id,
                query,
                result_id,
                feedback_type,
                comment,
                rating,
                user_role,
                username,
                created_at
            )
            VALUES (
                CAST(:id AS uuid),
                :query,
                :result_id,
                :feedback_type,
                :comment,
                :rating,
                :user_role,
                :username,
                NOW()
            )
            """
        )
        async with db_manager.get_postgres_session() as session:
            await session.execute(
                sql,
                {
                    "id": feedback_id,
                    "query": feedback.query,
                    "result_id": feedback.result_id,
                    "feedback_type": feedback.feedback_type,
                    "comment": feedback.comment,
                    "rating": feedback.rating,
                    "user_role": getattr(current_user, "role", None),
                    "username": getattr(current_user, "username", None),
                },
            )

        return FeedbackResponse(
            feedback_id=feedback_id,
            message="Feedback submitted.",
        )
