from sqlalchemy import Column, Integer, String, Float, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from datetime import datetime
from apps.api.database import Base

class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"
    id = Column(Integer, primary_key=True, index=True)
    model_version = Column(String, index=True)
    status = Column(String, default="pending")
    created_at = Column(DateTime, default=datetime.utcnow)
    metrics = relationship("EvaluationMetric", back_populates="run")

class EvaluationMetric(Base):
    __tablename__ = "evaluation_metrics"
    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(Integer, ForeignKey("evaluation_runs.id"))
    metric_name = Column(String, index=True)
    value = Column(Float)
    run = relationship("EvaluationRun", back_populates="metrics")
