from ..storage import JobRepository


class JobQueryService:
    def __init__(self, repository: JobRepository):
        self.repository = repository

    def jobs(self) -> list[dict]:
        return self.repository.list_all_jobs()

    def job(self, job_id: int) -> dict:
        return self.repository.get_job_with_match(job_id)

    def recommendations(self, recommendation_date: str | None = None) -> list[dict]:
        return self.repository.list_recommended_jobs(recommendation_date)

    def stats(self) -> dict[str, int]:
        return {
            "jobs": self.repository.count_jobs(),
            "recommendations": self.repository.count_recommended_jobs(),
        }
