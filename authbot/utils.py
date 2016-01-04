from threading import Thread, Event

class PeriodicTimer(Thread):
    def __init__(self, period, callback, args=(), kwargs={}):
        Thread.__init__(self, daemon=True)
        self.period = period
        self.callback = callback
        self.args = args
        self.kwargs = kwargs
        self._event = Event()

    def run(self):
        while not self._event.wait(self.period):
            self.callback(*self.args, **self.kwargs)

    def stop(self):
        self._event.set()
