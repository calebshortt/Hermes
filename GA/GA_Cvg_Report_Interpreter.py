
# 
# Genetic Algorithm Coverage Report Interpreter
# 
# Description:
#
# This program takes the latest coverage report from the 'Reports' directory and uses the coverage metrics 
# contained within to determine the format of the next sulley protocol definition.
# 
# The protocol definition creator is initialized and used to construct the templates
# 
# 
# Author:
#  			Caleb Shortt, 2013


from deap import creator, base, tools
import random, os, imp, time
from datetime import datetime, timedelta
import traceback

from PD_Creator.Protocol_Definition_Creator import PDef_Creator
from PD_Creator.PD_Helpers import HelperFunctions
from Config.analysis import DETAILS
from CvgHelpers import EMMAXMLParser
from Config.fuzzserver import DETAILS as FUZZCONFIG


class CVG_Max():

	def __init__(self, fuzz_server):

		# The fuzz server and all its functions (/Fuzz_Server/fuzzer_lib.py)
		self.Fuzz_Server = fuzz_server

		# Server timeout in seconds
		self.TIMEOUT = 60

		# Initialize a protocol definition creator
		self.pd_creator = PDef_Creator()

		# Initialize the helper functions and get the list of targets from the analyzer
		self.helper_functions = HelperFunctions()
		self.target_list = self.helper_functions.loadPickledFile(DETAILS.PATH_TO_ANALYZER + DETAILS.TARGET_FILENAME)

		# Initialize an EMMA XML Parser and give it the targets we want
		self.emma_xml_parser = EMMAXMLParser([target.name for target in self.target_list])

		# Granularity of analysis: 0=Package Level, 1=Source File Level, 2=Class Level, 3=Method Level
		self.PACKAGE_LEVEL	= "package"
		self.SRCFILE_LEVEL	= "srcfile"
		self.CLASS_LEVEL	= "class"
		self.METHOD_LEVEL	= "method"

		self.CVG_GRANULARITY_LIST = [self.PACKAGE_LEVEL, self.SRCFILE_LEVEL, self.CLASS_LEVEL, self.METHOD_LEVEL]

		# Change this variable to change the chosen granularity (index of above list)
		self.GRANULARITY = 0


		# Coverage Focus
		self.FOCUS_CLASS_CVG = "class"
		self.FOCUS_METHOD_CVG = "method"
		self.FOCUS_BLOCK_CVG = "block"
		self.FOCUS_LINE_CVG = "line"

		self.CVG_FOCUSES = [self.FOCUS_CLASS_CVG, self.FOCUS_METHOD_CVG, self.FOCUS_BLOCK_CVG, self.FOCUS_LINE_CVG]

		# Change this variable to change the coverage focus (index of above list)
		self.CVG_FOCUS = 3

		# -------------------------------------------------------------------------------------------------------------------
		#		Start of Genetic Algorithm Code (Still in Constructor)
		# -------------------------------------------------------------------------------------------------------------------

		# Create a maximizing fitness parameter for coverage
		creator.create("FitnessMax", base.Fitness, weights=(1.0,))

		# Each individual will be a list of flags that say which attribute is added, and which is not
		creator.create("Individual", list, fitness=creator.FitnessMax)

		# Right now there are 7 features for each individual (In this order):
		# [Links Enabled, imgs enabled, divs enabled, iframes enabled, objects enabled, js enabled, applets enabled]
		INDIVIDUAL_SIZE = 7

		# Create a population of individuals with random init values
		self.toolbox = base.Toolbox()
		self.toolbox.register("attr_bool", random.randint, 0, 1)
		self.toolbox.register("individual", tools.initRepeat, creator.Individual, self.toolbox.attr_bool, n=INDIVIDUAL_SIZE)
		self.toolbox.register("population", tools.initRepeat, list, self.toolbox.individual)

		self.toolbox.register("mate", tools.cxTwoPoints)
		self.toolbox.register("mutate", tools.mutFlipBit, indpb=0.05)
		self.toolbox.register("select", tools.selTournament, tournsize=3)
		self.toolbox.register("evaluate", self.evaluate)




	# -------------------------------------------------------------------------------------------------------------------
	# This function evaluates the given individual (list of flags) based on its performance in the fuzz server
	def evaluate(self, individual):
		# note the date and time
		# Get protocol definition from PD_Creator given the individual
		# Initialize and run the fuzz server - server will run for x amount of mutations (or some time limit)
		# wait for a file to be created in the Coverage/Reports directory that was created after the noted date and time
		# load that coverage (EMMA) file
		# 		Note that there are different types of coverage: class, method, block, and line coverage
		#		Might be able to target a different coverage given the type of bug we're looking for
		# extract the desired coverage type
		# return the number (%) coverage as an int

		print 'Individual: ' + str(individual)

		# Get the current time, this will be used to find the latest coverage report
		started_at = datetime.now()

		# try to get the protocol definition for the given individual
		try:
			self.pd_creator.reset()
			pdef = self.pd_creator.genAdvancedHTML(individual)
			#pdef = self.pd_creator.genStaticHTMLPageWithOneAnchor()
		except Exception as ex:
			print 'An unexpected exception occurred while generating the protocol definition.\n%s\n' % (str(ex))

		# try to save the generated protocol definition
		if pdef:
			self.pd_creator.save_protocol(pdef)
		else:
			raise Exception("No Protocol Definition Created")

		# Attempt to load the auto-generated protocol definition into sulley and run the fuzz server
		try:
			self.Fuzz_Server.reset()
			self.Fuzz_Server.reloadSulleyRequest()
			self.Fuzz_Server.run()
		except Exception as e:
			print 'An unexpected error has occurred while evaluating the fuzz server.\n%s\n' % (str(e))
			traceback.print_exc()


		# Get the latest coverage report from EMMA
		report_file = self.get_latest_cvg_report()
		report_created = datetime.fromtimestamp(os.stat(report_file).st_mtime)

		# If the report was NOT created after the 'started_at' timestamp, wait for the new results to show up
		# This might take a while since it is transferred to the coverage listener which saves it to file
		if started_at > report_created:
			print 'Waiting for coverage report to finish writing'

		timeout_time = datetime.now() + timedelta(minutes=self.TIMEOUT)
		while (started_at > report_created) and (datetime.now() < timeout_time):
			time.sleep(1)
			print '.',
			report_file = self.get_latest_cvg_report()
			report_created = datetime.fromtimestamp(os.stat(report_file).st_mtime)

		# Now we have the proper coverage report for the evaluation we just did
		# Now extract the selected coverage metrics and return them

		print '\nAnalyzing Coverage Report.'

		report_xml = ""
		with open(report_file, "r") as f:
			report_xml = f.read()


		# Extract the target information, parse the results, and format them in a TargetData tree structure
		# NOTE: target_data is a list of TargetData objects
		self.emma_xml_parser.extractEMMAData(report_xml)
		target_data = self.emma_xml_parser.getTargetResults()

		nov = 0
		cc = 0.0
		mc = 0.0
		bc = 0.0
		lc = 0.0
		for data in target_data:
			(tmp_nov, tmp_cc, tmp_mc, tmp_bc, tmp_lc) = self.getTargetCoverageValues(data)
			nov = nov + tmp_nov
			cc = cc + tmp_cc
			mc = mc + tmp_mc
			bc = bc + tmp_bc
			lc = lc + tmp_lc

			# DEBUG --------------------------------------------------------------------------
			#print "-"*40
			#print "NOV: " + str(nov) + ", cc: " + str(cc) + ", mc: " + str(mc) + ", bc: " + str(bc) + ", lc: " + str(lc)
			#print "-"*40


		return_value = 0.0
		if self.CVG_FOCUSES[self.CVG_FOCUS] == self.FOCUS_CLASS_CVG:
			return_value = cc/nov
		if self.CVG_FOCUSES[self.CVG_FOCUS] == self.FOCUS_METHOD_CVG:
			return_value = mc/nov
		if self.CVG_FOCUSES[self.CVG_FOCUS] == self.FOCUS_BLOCK_CVG:
			return_value = bc/nov
		if self.CVG_FOCUSES[self.CVG_FOCUS] == self.FOCUS_LINE_CVG:
			return_value = lc/nov

		# DEBUG ---------------------------------------------
		print "Coverage Value (" + str(self.CVG_FOCUSES[self.CVG_FOCUS]) + " coverage, " + self.CVG_GRANULARITY_LIST[self.GRANULARITY] +  " granularity): " + str(return_value)

		logfile = "%scvg_log%s.txt" % (FUZZCONFIG.SERVER_LOG_PATH, time.time())
		with open(logfile, 'w') as f:
			txt = "Coverage Value (" + str(self.CVG_FOCUSES[self.CVG_FOCUS]) + " coverage, " + self.CVG_GRANULARITY_LIST[self.GRANULARITY] +  " granularity): " + str(return_value)
			txt = txt + '\n\nOther Values:\n\n'
			txt = txt + 'Number of Values (nov): ' + str(nov) + '\n'
			txt = txt + 'Class CVG (cc): ' + str(cc) + '\n'
			txt = txt + 'Method CVG (mc): ' + str(mc) + '\n'
			txt = txt + 'Block CVG (bc): ' + str(bc) + '\n'
			txt = txt + 'Line CVG (lc): ' + str(lc) + '\n'
			f.write(txt)
			print 'Coverage log saved to %s' % (logfile)



		return return_value



	# -------------------------------------------------------------------------------------------------------------------
	# Calculates the average coverage of the given targets at the set granularity level
	# granularity is set by the self.GRANULARITY variable
	# returns the sum of the coverages and the number of calculated values. the avg is easily calculated from this
	# returned data format: (<num_of_values>, <class cvg>, <method cvg>, <block cvg>, <line cvg>)
	def getTargetCoverageValues(self, target_data):
		num_of_values = 0
		class_cvg = 0.0
		method_cvg = 0.0
		block_cvg = 0.0
		line_cvg = 0.0

		#print 'Type: ' + target_data.type + ', target type: ' + self.CVG_GRANULARITY_LIST[self.GRANULARITY] + ', ' + str(target_data.type == self.CVG_GRANULARITY_LIST[self.GRANULARITY])

		if target_data.type == self.CVG_GRANULARITY_LIST[self.GRANULARITY]:
			class_cvg = target_data.class_coverage
			method_cvg = target_data.method_coverage
			block_cvg = target_data.block_coverage
			line_cvg = target_data.line_coverage
			num_of_values = 1

		for child in target_data.children:
			(tmp_nov, tmp_cc, tmp_mc, tmp_bc, tmp_lc) = self.getTargetCoverageValues(child)
			num_of_values = num_of_values + tmp_nov
			class_cvg = class_cvg + tmp_cc
			method_cvg = method_cvg + tmp_mc
			block_cvg = block_cvg + tmp_bc
			line_cvg = line_cvg + tmp_lc

		return (num_of_values, class_cvg, method_cvg, block_cvg, line_cvg)






	# -------------------------------------------------------------------------------------------------------------------
	# Find the latest coverage report in the specified directory
	# from http://ubuntuforums.org/showthread.php?t=1526010
	def get_latest_cvg_report(self, path="GA/Reports/"):
		filelist = os.listdir(path)
		filelist = filter(lambda x: not os.path.isdir(path + str(x)), filelist)


		# TODO: Might want to make it so that the coverage reports (xml) are stored in their own
		#		directory for each run, then we can just grab all of the files, parse them, and average 
		#		the results

		# Reason:
		#		What if there are multiple files from the same test run?

		newest = max(filelist, key=lambda x: os.stat(path + str(x)).st_mtime)
		return path + newest



	# -------------------------------------------------------------------------------------------------------------------
	def run_algorithm(self):
		# probability of crossing two individuals (mate), mutation probability, number of generations
		CXPB, MUTPB, NGEN = 0.5, 0.2, 30

		# was 50 before
		POP_SIZE = 10
		random.seed(64)

		# Set the population size (number of individuals per generation) - each will have to be evaluated
		pop = self.toolbox.population(n=POP_SIZE)

		print 'Starting Evolution Algorithm...'

		fitnesses = map(self.toolbox.evaluate, pop)
		for ind, fit in zip(pop, fitnesses):
			ind.fitness.values = fit

		for g in range(NGEN):
			# Select the next generation of individuals
			offspring = self.toolbox.select(pop, len(pop))
			offspring = map(self.tool.clone, offspring)

			# Apply the crossover function (mate) to the new generation and reset the parents' fitness values
			for child1, child2 in zip(offspring[::2], offspring[1::2]):
				if random.random() < CXPB:
					self.toolbox.mate(child1, child2)
					del child1.fitness.values
					del child2.fitness.values

			# Apply mutation function - reset any mutant's fitness values
			for mutant in offspring:
				if random.random() < MUTPB:
					self.toolbox.mutate(mutant)
					del mutant.fitness.values

			# Only evaluate the individuals who have invalid fitness values
			invalid_ind = [ind for ind in offspring if not ind.fitness.valid]
			fitnesses = map(self.toolbox.evaluate, invalid_ind)
			for ind, fit in zip(invalid_ind, fitnesses):
				ind.fitness.values = fit

			# The new population is the generated offspring and mutants
			pop[:] = offspring


		# Run some numbers to see the stats
		fits = [ind.fitness.values[0] for ind in pop]

		length = len(pop)
		mean = sum(fits) / length
		sum2 = sum(x*x for x in fits)
		std = abs(sum2 / length - mean**2)**0.5

		print 'Algorithm Execution Final Population Results'
		print 'Max: ' + str(max(fits))
		print 'Min: ' + str(min(fits))
		print 'Avg: ' + str(mean)
		print 'StD: ' + str(std)

		return pop



# DEBUG
#lib = imp.load_source('*', '../Fuzz_Server/fuzzer_lib.py')
#f = FuzzServer()
#test = CVG_Max(f)

#test.evaluate()



		




















