import os
import re
import os.path
import json
import argparse
import pprint
from LogManager import logger, initConsoleLogging

# regular  expression for fields
START_OF_RECORD = re.compile('^(?P<name>NUMBER): ')
GENERIC_START_OF_RECORD = re.compile('^( +)?(?P<name>[A-Z/]+( [A-Z/#]+)*): ')
DBA_COMMENTS = re.compile('^( +)?(?P<name>DBA Comments): ')
GENERIC_FIELD_RECORD = re.compile('( )(?P<name>[A-Z/]+( [A-Z/#]+)*): ')
# This is dictories of all possible sub-files in the schema
ICR_FILE_KEYWORDS = set([
    'NUMBER',
    'ID',
    'IA #',
    'FILE NUMBER',
    'GLOBAL ROOT',
    'DATE CREATED',
    'CUSTODIAL PACKAGE',
    'CUSTODIAL ISC',
    'USAGE',
    'TYPE',
    'DBIC APPROVAL STATUS',
    'NAME',
    'ROUTINE',
    'ORIGINAL NUMBER',
    # SUB_ID
    'CREATOR',
    'GENERAL DESCRIPTION',
    'STATUS',
    'DURATION',
    'MAIL MESSAGE',
    'GOOD ONLY FOR VERSION',
    'DBA Comments',
    'EDITOR'
])

SUBFILE_FIELDS = {
    'GLOBAL REFERENCE': [
        'FIELD NUMBER',
        'GLOBAL DESCRIPTION'
    ],
    'COMPONENT/ENTRY POINT': [
        'COMPONENT DESCRIPTION',
        'VARIABLES'
    ],
    'VARIABLES': [
        'TYPE',
        'VARIABLES DESCRIPTION'
    ],
    'SUBSCRIBING PACKAGE': [
        'ISC',
        'SUBSCRIBING DETAILS'
    ],
    'DATE/TIME EDITED': [
        'ACTION',
        'AT THE REQUEST OF',
        'WITH CONCURRENCE OF'
    ],
    'EDITOR': [
    ],
    'KEYWORDS': [
    ],
    'FIELD NUMBER': [
        'FIELD NAME',
        'ACCESS',
        'FIELD DESCRIPTION',
        'LOCATION'
    ]
}

SUBFILE_KEYWORDS = reduce(set.union, [set(y) for y in SUBFILE_FIELDS.itervalues()], set()) | set([x for x in SUBFILE_FIELDS.iterkeys()])

ICR_FILE_KEYWORDS = ICR_FILE_KEYWORDS | SUBFILE_KEYWORDS

class ICRParser(object):
    def __init__(self):
        self._totalRecord = 0 # total number of record
        self._curRecord = None # current record object
        self._outObject = [] # store output result
        self._curLineNo = 0
        self._curField = None
        self._curStack = []
    def parse(self, inputFilename, outputFilename):
        with open(inputFilename,'r') as ICRFile:
            for line in ICRFile:
                line = line.rstrip("\r\n")
                self._curLineNo +=1

                match = START_OF_RECORD.match(line)
                if match:
                    self._startOfNewItem(match, line)
                    continue
                match = GENERIC_START_OF_RECORD.search(line)
                if not match:
                    match = DBA_COMMENTS.match(line)
                if match and match.group('name') in ICR_FILE_KEYWORDS:
                    fieldName = match.group('name')
                    self._curField = fieldName
                    if self._isSubFile(fieldName):
                        self._startOfSubFile(match, line)
                    else:
                        # figure out where to store the record
                        self._rewindStack();
                        self._findKeyValueInLine(match, line, self._curRecord)
                elif self._curField and self._curField in self._curRecord:
                    if not (type(self._curRecord[self._curField]) is list):
                        preVal = self._curRecord[self._curField]
                        self._curRecord[self._curField] = []
                        self._curRecord[self._curField].append(preVal)
                    self._curRecord[self._curField].append(line)
                else:
                    if self._curRecord:
                        if len(line.strip()) == 0:
                            continue
                        print 'No field associated with line %s: %s ' % (self._curLineNo, line)
        logger.debug('End of file now')
        if len(self._curStack) > 0:
            self._curField = None
            self._rewindStack()
            logger.debug('Add last record: %s', self._curRecord)
            self._outObject.append(self._curRecord)
        # pprint.pprint(self._outObject);
        with open(outputFilename, 'w') as out_file:
            json.dump(self._outObject,out_file, indent=4)
    def _isSubFile(self, field):
        return field in SUBFILE_FIELDS
    def _isSubFileField(self, subFile, field):
        return self._isSubFile(subFile) and field in SUBFILE_FIELDS[subFile]
    def _startOfNewItem(self, matchObj, line):
        logger.debug('Starting of new item: %s', self._curStack)
        self._curField = None

        self._rewindStack()
        if self._curRecord:
            self._outObject.append(self._curRecord)
        self._curRecord = {}
        self._findKeyValueInLine(matchObj, line, self._curRecord)
        #pprint.pprint(self._curRecord)
    def _findKeyValueInLine(self, match, line, outObj):
        """ parse all name value pair in a line and put back in outObj"""
        name = match.group('name'); # this is the name part
        # now find if there is any other name value pair in the same line
        restOfLine = line[match.end():]
        allmatches = []
        for m in GENERIC_FIELD_RECORD.finditer(restOfLine):
            allmatches.append(m);
        if allmatches:
            for idx, rm in enumerate(allmatches):
                if idx == 0:
                    outObj[name] = restOfLine[:rm.start()].strip()
                if idx == len(allmatches) -1 :
                    outObj[rm.group('name')] = restOfLine[rm.end():].strip()
                else:
                    outObj[allmatches[idx-1].group('name')] = restOfLine[allmatches[idx-1].end():rm.start()].strip()
        else:
            outObj[name] = line[match.end():].strip()

    def _startOfSubFile(self, match, line):
        """
            for start of the sub file, we need to add a list element to the current record if it not there
            reset _curRecord to be a new one, and push old one into the stack
        """
        subFile = match.group('name')
        logger.debug('Start parsing subFile: %s, %s', subFile, line)
        while len(self._curStack) > 0: # we are in subfile mode
            prevSubFile = self._curStack[-1][1]
            if prevSubFile == subFile: # just continue with more of the same subfile
                self._curStack[-1][0].setdefault(subFile, []).append(self._curRecord) # append the previous result
                logger.debug('append previous record the current stack')
                break;
            else: # this is a different subfile # now check if it is a nested subfile
                if self._isSubFileField(prevSubFile, subFile): # this is a nested subFile, push to stack
                    logger.debug('Nested subFile, push to the stack')
                    self._curStack.append((self._curRecord, subFile))
                    logger.debug('Nested subFile, stack is %s', self._curStack)
                    break;
                else: # this is a different subFile now:
                    logger.debug('different subFile')
                    preStack = self._curStack.pop()
                    logger.debug('Pop stack')
                    preStack[0].setdefault(preStack[1], []).append(self._curRecord)
                    self._curRecord = preStack[0]
                    logger.debug('different subFile, stack is %s', self._curStack)
        if len(self._curStack) == 0:
            self._curStack.append((self._curRecord, subFile)) # push a tuple, the first is the record, the second is the subFile field
            logger.debug('push to stack: %s', self._curStack)
        self._curRecord = {}
        self._findKeyValueInLine(match, line, self._curRecord)
    def _rewindStack(self):
        logger.debug('rewindStack is called')
        while len(self._curStack) > 0: # we are in subFile Mode
            if not self._isSubFileField(self._curStack[-1][1], self._curField):
                preStack = self._curStack.pop()
                logger.debug('pop previous stack item: %s', preStack)
                preStack[0].setdefault(preStack[1],[]).append(self._curRecord)
                logger.debug('reset current record: %s', preStack)
                self._curRecord = preStack[0]
            else:
                logger.debug('in subFile Fields: %s, record: %s', self._curField, self._curRecord)
                break


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='VistA ICR File Parser')
    parser.add_argument('icrfile', help='path to the VistA ICR file')
    parser.add_argument('outJson', help='path to the output JSON file')
    result = parser.parse_args()
    initConsoleLogging()
    if result.icrfile:
        icrParser = ICRParser()
        icrParser.parse(result.icrfile, result.outJson)