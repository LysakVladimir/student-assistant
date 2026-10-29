from backend.app.services import find_windows

class FakeLesson:
    def __init__(self, end, start):
        self.end_time = end
        self.start_time = start

def test_find_windows_filters_short_gaps():
    lessons = [
        FakeLesson("09:30", "09:00"),
        FakeLesson("10:30", "10:00"),
        FakeLesson("12:00", "11:30"),
    ]
    windows = find_windows(lessons, threshold=40)
    assert windows == [{"from": "10:30", "to": "11:30", "minutes": 60}]
