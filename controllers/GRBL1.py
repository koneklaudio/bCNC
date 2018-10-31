class Controller:
	def __init__(self, master):
		self.master = master
		print("grbl1 loaded")

	def test(self):
		print("grbl1 test")

	def executeCommand(self, line):
		return False

	def hardResetPre(self):
		pass

	def hardResetAfter(self):
		pass

	def viewSettings(self):
		self.master.sendGCode("$$")

	def viewBuild(self):
		self.master.sendGCode("$I")

	def viewStartup(self):
		self.master.sendGCode("$N")

	def checkGcode(self):
		self.master.sendGCode("$C")

	def grblHelp(self):
		self.master.sendGCode("$")

	def grblRestoreSettings(self):
		self.master.sendGCode("$RST=$")

	def grblRestoreWCS(self):
		self.master.sendGCode("$RST=#")

	def grblRestoreAll(self):
		self.master.sendGCode("$RST=#")

	def purgeController(self):
		time.sleep(1)
		self.master.unlock(False)
